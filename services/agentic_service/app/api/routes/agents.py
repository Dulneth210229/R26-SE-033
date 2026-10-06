"""
Agent routes.

For now, this file contains placeholder endpoints.

Later, each endpoint will call the real agent class:
- RequirementAgent
- DomainAgent
- ArchitectureAgent
- UIUXAgent
- CoderAgent

At this foundation step, we only verify the API structure.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Body, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.enums import AgentName
from app.schemas.agent_schema import AgentRunRequest, AgentRunResponse
from app.services.in_memory_store import store
from app.agents.requirement_agent.agent import requirement_agent
from app.agents.domain_agent.agent import domain_agent
from app.agents.architecture_agent.agent import architecture_agent
from app.agents.uiux_agent.agent import uiux_agent
from app.agents.coder_agent.agent import coder_agent
from app.agents.coder_agent.schemas import CoderAgentEnvSaveResult
from app.agents.security_agent.agent import security_agent
from app.agents.qa_agent.agent import qa_agent
from app.core.enums import AgentName, ArtifactType, ArtifactFormat
from app.schemas.agent_schema import AgentRunRequest, AgentRunResponse
from app.services.artifact_service import artifact_service
from app.schemas.requirement_schema import (
    RequirementAgentRunRequest,
    RequirementAgentReviseRequest,
)
from app.schemas.requirement_conversation_schema import (
    RequirementConversationConfirmRequest,
    RequirementConversationReplyRequest,
    RequirementConversationState,
)
from app.schemas.domain_schema import (
    DomainAgentRunRequest,
    DomainAgentReviseRequest,
)
from app.schemas.architecture_schema import (
    ArchitectureAgentRunRequest,
    ArchitectureAgentReviseRequest,
)
from app.schemas.uiux_schema import UIUXAgentReviseRequest, UIUXAgentRunRequest
from app.schemas.coder_schema import CoderAgentRunRequest, CoderAgentReviseRequest
from app.schemas.security_schema import (
    SecurityAgentRunRequest,
    SecurityChatHistoryResponse,
    SecurityChatMessageRequest,
    SecurityChatTurn,
)
from app.schemas.qa_schema import QAAgentRunRequest, QAChatHistoryResponse, QAChatMessageRequest, QAChatTurn
from app.services.in_memory_store import store
from app.services.plantuml_service import plantuml_service
from app.services.stage_event_service import stage_event_service
import traceback

router = APIRouter(prefix="/features/{feature_id}/agents", tags=["Agents"])


def _validate_feature(feature_id: str, current_user: dict):
    """
    Look up a feature and verify the signed-in user owns its parent project -- 404 (not 403)
    both when the feature doesn't exist and when it belongs to someone else, so a user can't
    distinguish the two by probing IDs. A feature whose project has no user_id at all
    (pre-migration legacy data, see scripts/migrate_existing_projects_to_user.py) is treated as
    accessible to any signed-in user rather than locked out -- mirrors projects.py's identical
    reasoning.
    """
    feature = store.features.get(feature_id)

    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    project = store.projects.get(feature["project_id"])
    owner_id = project.get("user_id") if project else None

    if not project or (owner_id is not None and owner_id != current_user["user_id"]):
        raise HTTPException(status_code=404, detail="Feature not found")

    return feature


def _readable_error(error: Exception) -> str:
    """
    str(error) is frequently EMPTY for transport/timeout exceptions -- e.g. httpx.ReadTimeout is
    often raised by httpx's internals with no message at all. Confirmed as the real cause of a
    reported "Architecture Agent failed: " banner with nothing after the colon (a real request
    that timed out mid-repair-call). Every generic `except Exception` handler in this file that
    builds a user-facing message uses this instead of a bare str(error), so a human always sees
    something actionable (at minimum the exception's class name) instead of a blank message.
    """
    return str(error) or f"{type(error).__name__} (no further detail was provided by the error itself)"


@router.post("/requirement/run", response_model=AgentRunResponse)
async def run_requirement_agent(
    feature_id: str,
    request: RequirementAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Run the Requirement Agent.

    This endpoint:
    - receives structured BA input
    - supports architectural_style input
    - calls the selected LLM provider
    - generates SRS Markdown and SRS JSON
    - saves both files as artifacts
    - returns artifact IDs

    Human approval is required after this.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.REQUIREMENT, "run", request.human_comment)

    try:
        return await requirement_agent.run(
            feature_id=feature_id,
            request=request
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        print("========== REQUIREMENT AGENT ERROR ==========")
        print(traceback.format_exc())
        print("============================================")

        raise HTTPException(
            status_code=500,
            detail=f"Requirement Agent failed: {_readable_error(error)}"
        )

@router.post("/requirement/revise", response_model=AgentRunResponse)
async def revise_requirement_agent(
    feature_id: str,
    request: RequirementAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Revise the latest Requirement Agent SRS.

    This endpoint:
    - loads the latest SRS JSON artifact
    - applies the human revision comment
    - creates a new SRS version
    - keeps previous versions unchanged
    """

    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.REQUIREMENT, "revise", request.revision_comment, request.revised_by
    )

    try:
        return await requirement_agent.revise(
            feature_id=feature_id,
            request=request
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Requirement Agent revision failed: {_readable_error(error)}"
        )


@router.post("/requirement/revise/stream")
async def revise_requirement_agent_stream(feature_id: str, request: RequirementAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /requirement/revise -- same newline-delimited JSON event shape as
    /requirement/conversation/confirm/stream and /requirement/conversation/reply/stream, so the
    frontend can show the agent's revision_summary reaction + the regenerated SRS "typing" live
    as they're generated instead of a blocking wait followed by a sudden reveal:
        {"type": "token", "text": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.REQUIREMENT, "revise", request.revision_comment, request.revised_by
    )

    async def event_stream():
        try:
            async for event in requirement_agent.revise_stream(
                feature_id=feature_id,
                revision_comment=request.revision_comment,
                revised_by=request.revised_by,
            ):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": f"Requirement Agent revision failed: {_readable_error(error)}"}
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


# ----------------------------------------------------------------------
# Requirement Agent conversational gap-filling loop -- fully additive, alongside (not replacing)
# /requirement/run and /requirement/revise above. See RequirementAgent.start_conversation/
# reply_to_conversation/get_conversation/reset_conversation/confirm_conversation for the actual
# logic; these routes only validate the feature exists and record the stage_event "ask" half of
# the activity timeline, matching the existing route pattern.
# ----------------------------------------------------------------------

@router.post("/requirement/conversation/start", response_model=RequirementConversationState)
async def start_requirement_conversation(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Begin (or resume) a requirement-gathering conversation for this feature, seeded from its
    rough feature_description.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.REQUIREMENT, "clarify_start", None)

    try:
        return await requirement_agent.start_conversation(feature_id=feature_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to start requirement conversation: {_readable_error(error)}")


@router.post("/requirement/conversation/reply", response_model=RequirementConversationState)
async def reply_to_requirement_conversation(feature_id: str, request: RequirementConversationReplyRequest, current_user: dict = Depends(get_current_user)):
    """
    Answer the current batch of clarifying questions (or add free-form additional information).
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.REQUIREMENT, "clarify", request.reply)

    try:
        return await requirement_agent.reply_to_conversation(feature_id=feature_id, request=request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to continue requirement conversation: {_readable_error(error)}")


@router.post("/requirement/conversation/reply/stream")
async def reply_to_requirement_conversation_stream(feature_id: str, request: RequirementConversationReplyRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /requirement/conversation/reply -- same newline-delimited JSON event
    shape as /requirement/conversation/confirm/stream, so the frontend can show the agent's
    reaction+questions "typing" live as they're generated instead of a blocking wait followed by
    a sudden reveal:
        {"type": "token", "text": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "state": {...}}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.REQUIREMENT, "clarify", request.reply)

    async def event_stream():
        try:
            async for event in requirement_agent.reply_to_conversation_stream(
                feature_id=feature_id, reply_text=request.reply
            ):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": f"Failed to continue requirement conversation: {_readable_error(error)}"}
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/requirement/conversation/reply/upload", response_model=RequirementConversationState)
async def reply_to_requirement_conversation_with_document(
    feature_id: str,
    file: UploadFile = File(...),
    reply: str | None = Form(None),
    current_user: dict = Depends(get_current_user),
):
    """
    Same as /requirement/conversation/reply, but the human's answer is (also) an attached
    text/PDF/DOCX/MD document -- its full text is extracted and handed to the same gap-analysis
    call, so the agent can scrape requirements directly out of an existing brief instead of the
    human retyping it by hand.
    """
    _validate_feature(feature_id, current_user)
    file_bytes = await file.read()
    stage_event_service.record(
        feature_id,
        AgentName.REQUIREMENT,
        "clarify",
        f"{reply or ''}\n\n[Attached file: {file.filename}]".strip(),
    )

    try:
        return await requirement_agent.reply_to_conversation_with_document(
            feature_id=feature_id, file_bytes=file_bytes, filename=file.filename, reply_text=reply
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to process attached document: {_readable_error(error)}")


@router.post("/requirement/conversation/turns/{turn_index}/edit", response_model=RequirementConversationState)
async def edit_requirement_conversation_turn(
    feature_id: str, turn_index: int, request: RequirementConversationReplyRequest, current_user: dict = Depends(get_current_user)):
    """
    Edit an already-submitted reply and regenerate the conversation from that point forward --
    mirrors ChatGPT/Claude's "edit message" flow. Discards the edited turn and everything built
    on top of it.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.REQUIREMENT, "clarify", request.reply)

    try:
        return await requirement_agent.edit_turn_reply(
            feature_id=feature_id, turn_index=turn_index, new_reply=request.reply
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to edit requirement conversation turn: {_readable_error(error)}")


@router.post("/requirement/conversation/turns/{turn_index}/edit/stream")
async def edit_requirement_conversation_turn_stream(
    feature_id: str, turn_index: int, request: RequirementConversationReplyRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /requirement/conversation/turns/{turn_index}/edit -- same
    newline-delimited JSON event shape as /requirement/conversation/reply/stream, so an edited
    message's regenerated reaction+questions "type" in live instead of sitting behind a plain
    spinner for however long the real LLM call takes (a real reported gap: editing was the one
    reply-shaped action in this conversation that didn't stream, making it look stalled/broken on
    a slow model even though it was quietly still working):
        {"type": "token", "text": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "state": {...}}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.REQUIREMENT, "clarify", request.reply)

    async def event_stream():
        try:
            async for event in requirement_agent.edit_turn_reply_stream(
                feature_id=feature_id, turn_index=turn_index, new_reply=request.reply
            ):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": f"Failed to edit requirement conversation turn: {_readable_error(error)}"}
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/requirement/conversation", response_model=RequirementConversationState | None)
async def get_requirement_conversation(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Fetch the current conversation state (for reloading the page or polling) -- null if no
    conversation has been started yet for this feature.
    """
    _validate_feature(feature_id, current_user)
    return requirement_agent.get_conversation(feature_id=feature_id)


@router.post("/requirement/conversation/reset")
async def reset_requirement_conversation(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Discard the in-progress conversation for this feature and start over.
    """
    _validate_feature(feature_id, current_user)
    requirement_agent.reset_conversation(feature_id=feature_id)
    return {"feature_id": feature_id, "status": "reset"}


@router.post("/requirement/conversation/confirm", response_model=AgentRunResponse)
async def confirm_requirement_conversation(feature_id: str, request: RequirementConversationConfirmRequest, current_user: dict = Depends(get_current_user)):
    """
    Finalize the conversation into a real SRS -- generates and saves a normal ArtifactType.SRS
    version through the same path /requirement/run uses, so it requires human approval before
    Domain Agent can run, exactly like any other SRS.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.REQUIREMENT, "confirm", request.override_reason, request.confirmed_by)

    try:
        return await requirement_agent.confirm_conversation(feature_id=feature_id, request=request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to confirm requirement conversation: {_readable_error(error)}")


@router.post("/requirement/conversation/confirm/stream")
async def confirm_requirement_conversation_stream(feature_id: str, request: RequirementConversationConfirmRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of confirm -- same validation/generation/save logic
    (RequirementAgent.confirm_conversation_stream), but the response body is newline-delimited
    JSON events so the frontend can show the SRS "typing" live as it's generated, instead of a
    blocking wait followed by a sudden reveal. Each line is one JSON object:
        {"type": "token", "text": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "..."}

    A plain StreamingResponse (not SSE) is used deliberately: EventSource only supports GET with
    no request body, but confirming needs to POST override_quality_gate/override_reason -- a
    fetch() ReadableStream reader on the frontend handles a streamed POST response body just as
    well for this one-directional, single-request use case.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.REQUIREMENT, "confirm", request.override_reason, request.confirmed_by
    )

    async def event_stream():
        try:
            async for event in requirement_agent.confirm_conversation_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": f"Failed to confirm requirement conversation: {_readable_error(error)}"}
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/domain/run", response_model=AgentRunResponse)
async def run_domain_agent(
    feature_id: str,
    request: DomainAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Run the Domain Agent.

    This endpoint:
    - requires an approved SRS JSON artifact
    - retrieves relevant domain knowledge (RAG) from the vector store
    - generates Enhanced SRS Markdown, Enhanced SRS JSON, and Domain Improvements JSON

    Human approval is required after this before Architecture Agent can use the Enhanced SRS.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.DOMAIN, "run", request.human_comment)

    try:
        return await domain_agent.run(
            feature_id=feature_id,
            request=request
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        print("========== DOMAIN AGENT ERROR ==========")
        print(traceback.format_exc())
        print("=========================================")

        raise HTTPException(
            status_code=500,
            detail=f"Domain Agent failed: {_readable_error(error)}"
        )


@router.post("/domain/run/stream")
async def run_domain_agent_stream(feature_id: str, request: DomainAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /domain/run -- same newline-delimited JSON event shape as the
    Requirement Agent's streaming endpoints, so the frontend can show the enrichment plan
    "typing" live instead of a blocking wait followed by a sudden reveal:
        {"type": "token", "text": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.DOMAIN, "run", request.human_comment)

    async def event_stream():
        try:
            async for event in domain_agent.run_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"Domain Agent failed: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/domain/revise", response_model=AgentRunResponse)
async def revise_domain_agent(
    feature_id: str,
    request: DomainAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Revise the latest Domain Agent Enhanced SRS.

    This endpoint:
    - loads the latest Enhanced SRS JSON artifact
    - applies the human revision comment
    - creates a new Enhanced SRS version
    - keeps previous versions unchanged
    """

    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.DOMAIN, "revise", request.revision_comment, request.revised_by
    )

    try:
        return await domain_agent.revise(
            feature_id=feature_id,
            request=request
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("========== DOMAIN AGENT REVISION ERROR ==========")
        print(traceback.format_exc())
        print("===================================================")

        raise HTTPException(
            status_code=500,
            detail=f"Domain Agent revision failed: {_readable_error(error)}"
        )


@router.post("/domain/revise/stream")
async def revise_domain_agent_stream(feature_id: str, request: DomainAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /domain/revise -- same newline-delimited JSON event shape as
    /domain/run/stream.
        {"type": "token", "text": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.DOMAIN, "revise", request.revision_comment, request.revised_by
    )

    async def event_stream():
        try:
            async for event in domain_agent.revise_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"Domain Agent revision failed: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/architecture/run", response_model=AgentRunResponse)
async def run_architecture_agent(
    feature_id: str,
    request: ArchitectureAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Run Architecture Agent.

    This endpoint:
    - requires approved SRS JSON
    - optionally uses approved Enhanced SRS JSON
    - generates Architecture Plan Markdown
    - generates Architecture Plan JSON
    - generates Use Case, Sequence, and Class Diagram PUML/PNG artifacts

    It does not generate a separate API contract.
    """

    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.ARCHITECTURE, "run", request.human_comment)

    try:
        return await architecture_agent.run(
            feature_id=feature_id,
            request=request
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Architecture Agent failed: {_readable_error(error)}"
        )
    


@router.post("/architecture/revise", response_model=AgentRunResponse)
async def revise_architecture_agent(
    feature_id: str,
    request: ArchitectureAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Revise the latest Architecture Agent output.

    This endpoint:
    - loads the latest Architecture Plan JSON
    - applies the human/client revision comment
    - regenerates Use Case, Sequence, and Class diagrams from the revised plan
    - creates a new Architecture Agent version
    - keeps previous versions unchanged
    """

    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.ARCHITECTURE, "revise", request.revision_comment, request.revised_by
    )

    try:
        return await architecture_agent.revise(
            feature_id=feature_id,
            request=request
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Architecture Agent revision failed: {_readable_error(error)}"
        )


@router.post("/architecture/run/stream")
async def run_architecture_agent_stream(feature_id: str, request: ArchitectureAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /architecture/run -- same newline-delimited JSON event shape as Domain
    Agent's streaming endpoints, plus a "phase" event during the non-streamable tail (use case
    model, diagram generation, PlantUML rendering) so the frontend can show real progress instead
    of a bare loader once the plan text itself has finished streaming:
        {"type": "token", "text": "..."}
        {"type": "phase", "phase": "...", "label": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.ARCHITECTURE, "run", request.human_comment)

    async def event_stream():
        try:
            async for event in architecture_agent.run_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"Architecture Agent failed: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/architecture/revise/stream")
async def revise_architecture_agent_stream(feature_id: str, request: ArchitectureAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /architecture/revise -- same newline-delimited JSON event shape as
    /architecture/run/stream.
        {"type": "token", "text": "..."}
        {"type": "phase", "phase": "...", "label": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.ARCHITECTURE, "revise", request.revision_comment, request.revised_by
    )

    async def event_stream():
        try:
            async for event in architecture_agent.revise_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": f"Architecture Agent revision failed: {_readable_error(error)}"}
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


    # ----------------------------------------------------
    # Ui/UX  Agent
    # ----------------------------------------------------
@router.post("/uiux/run", response_model=AgentRunResponse)
async def run_uiux_agent(feature_id: str, request: UIUXAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Run the UI/UX Agent.

    This endpoint:
    - requires an approved SRS JSON artifact and an approved Architecture Plan JSON artifact
    - optionally uses an approved Enhanced SRS JSON if available
    - generates ui_metadata, per-component code, and per-page preview screenshots

    No human approval is required after this -- every UI/UX artifact is saved already approved
    (per direct user request; see uiux_agent/agent.py's _save_artifacts). A human can still
    explicitly change the output afterward via POST .../uiux/revise (or its streaming variant).
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.UIUX, "run", request.human_comment)

    try:
        output = await uiux_agent.run(feature_id=feature_id, request=request)

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.UIUX,
            status="completed",
            message="UI/UX Agent completed. Pages, components, and previews were generated.",
            artifact_ids=output.artifact_ids,
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("========== UI/UX AGENT ERROR ==========")
        print(traceback.format_exc())
        print("========================================")

        raise HTTPException(
            status_code=500,
            detail=f"UI/UX Agent failed: {_readable_error(error)}"
        )


@router.post("/uiux/run/stream")
async def run_uiux_agent_stream(feature_id: str, request: UIUXAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /uiux/run -- same newline-delimited JSON event shape as Domain/
    Architecture Agent's streaming endpoints, so the frontend can show ui_metadata_json "typing"
    live, followed by {"type": "phase"} events for the non-streamable tail (component generation,
    page assembly/rendering):
        {"type": "token", "text": "..."}
        {"type": "phase", "phase": "...", "label": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.UIUX, "run", request.human_comment)

    async def event_stream():
        try:
            async for event in uiux_agent.run_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"UI/UX Agent failed: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/uiux/revise", response_model=AgentRunResponse)
async def revise_uiux_agent(feature_id: str, request: UIUXAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Revise the latest UI/UX Agent output via an explicit human-directed change.

    This endpoint:
    - loads the latest ui_metadata_json artifact
    - asks the LLM for a small, targeted plan of what should change (never a full retype)
    - regenerates only the affected components' HTML; every other component is carried over
      verbatim from the prior version
    - creates a new, already-approved version; previous versions are kept unchanged
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.UIUX, "revise", request.revision_comment, request.revised_by
    )

    try:
        output = await uiux_agent.revise(feature_id=feature_id, request=request)

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.UIUX,
            status="revised",
            message="UI/UX Agent revision completed. Only the affected components were regenerated.",
            artifact_ids=output.artifact_ids,
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("========== UI/UX AGENT REVISION ERROR ==========")
        print(traceback.format_exc())
        print("==================================================")

        raise HTTPException(
            status_code=500,
            detail=f"UI/UX Agent revision failed: {_readable_error(error)}"
        )


@router.post("/uiux/revise/stream")
async def revise_uiux_agent_stream(feature_id: str, request: UIUXAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /uiux/revise -- same newline-delimited JSON event shape as
    /uiux/run/stream.
        {"type": "token", "text": "..."}
        {"type": "phase", "phase": "...", "label": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.UIUX, "revise", request.revision_comment, request.revised_by
    )

    async def event_stream():
        try:
            async for event in uiux_agent.revise_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": f"UI/UX Agent revision failed: {_readable_error(error)}"}
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/coder/run", response_model=AgentRunResponse)
async def run_coder_agent(feature_id: str, request: CoderAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Run the Coder Agent.

    This endpoint calls the same CoderAgent.run() the LangGraph coder_node uses internally --
    it lets a human trigger an initial Coder Agent run directly (e.g. from the chat UI) instead
    of only ever reaching it by advancing the graph. This can take several minutes (planning +
    the agentic coding loop + sandboxed build/lint/test verification), same as /coder/revise.

    Human approval is required after this, same as after a revision.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.CODER, "run", request.human_comment)

    try:
        output = await coder_agent.run(feature_id=feature_id, request=request)

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.CODER,
            status="completed" if output.verification_passed else "completed_with_verification_failures",
            message=(
                "Coder Agent completed and verification passed. Requires human approval."
                if output.verification_passed
                else "Coder Agent completed but verification failed. Requires human review before approval."
            ),
            artifact_ids=output.artifact_ids,
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("========== CODER AGENT ERROR ==========")
        print(traceback.format_exc())
        print("========================================")

        raise HTTPException(
            status_code=500,
            detail=f"Coder Agent failed: {_readable_error(error)}"
        )


@router.post("/coder/revise", response_model=AgentRunResponse)
async def revise_coder_agent(feature_id: str, request: CoderAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Revise the latest Coder Agent output for this feature.

    This endpoint:
    - requires a prior Coder Agent run (a CODE_PLAN artifact and feature
      branch must already exist for this feature)
    - re-plans with the existing plan plus the human's revision comment
    - resumes the EXISTING feature branch (never resets it) so the
      revision builds on already-verified work instead of starting over
    - re-codes, re-verifies, and saves a new version of all Coder Agent
      artifacts -- the previous version stays intact and inspectable

    Human approval is required again after this, same as after a normal run.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.CODER, "revise", request.revision_comment, request.revised_by
    )

    try:
        output = await coder_agent.revise(feature_id=feature_id, request=request)

        if isinstance(output, CoderAgentEnvSaveResult):
            return AgentRunResponse(
                feature_id=feature_id,
                agent_name=AgentName.CODER,
                status="database_connection_saved",
                message=output.message,
                artifact_ids=[],
            )

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.CODER,
            status="revised" if output.verification_passed else "revised_with_verification_failures",
            message=(
                "Coder Agent revision completed and verification passed. "
                "A new version was created and requires human approval."
                if output.verification_passed
                else "Coder Agent revision completed but verification failed. "
                "A new version was created and requires human review before approval."
            ),
            artifact_ids=output.artifact_ids,
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("========== CODER AGENT REVISION ERROR ==========")
        print(traceback.format_exc())
        print("==================================================")

        raise HTTPException(
            status_code=500,
            detail=f"Coder Agent revision failed: {_readable_error(error)}"
        )


@router.post("/coder/run/stream")
async def run_coder_agent_stream(feature_id: str, request: CoderAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /coder/run -- same newline-delimited JSON event shape as
    Domain/Architecture Agent's streaming endpoints, plus a "phase" event during the
    non-streamable coding/verify tail (coding_loop.py's agentic loop has no token-level
    streaming at all) so the frontend can show real progress instead of a bare loader once
    the plan text itself has finished streaming:
        {"type": "token", "text": "..."}
        {"type": "phase", "phase": "...", "label": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "verification_passed": bool, "status": "...", "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.CODER, "run", request.human_comment)

    async def event_stream():
        try:
            async for event in coder_agent.run_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"Coder Agent failed: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/coder/revise/stream")
async def revise_coder_agent_stream(feature_id: str, request: CoderAgentReviseRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /coder/revise -- same newline-delimited JSON event shape as
    /coder/run/stream.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(
        feature_id, AgentName.CODER, "revise", request.revision_comment, request.revised_by
    )

    async def event_stream():
        try:
            async for event in coder_agent.revise_stream(feature_id=feature_id, request=request):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": f"Coder Agent revision failed: {_readable_error(error)}"}
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


    # ----------------------------------------------------
    # Security Agent
    # ----------------------------------------------------
@router.post("/security/run", response_model=AgentRunResponse)
async def run_security_agent(feature_id: str, request: SecurityAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Run the Security Agent -- scans the Coder Agent's generated workspace (pattern/secret/
    dependency layers plus an LLM review pass) and saves a versioned Critical/Moderate/Warning
    report. No human approval is required after this (auto-approved, soft-gate stage -- see
    security_agent/agent.py's own docstring): a Critical gate decision is clearly surfaced on the
    report for a human to act on (e.g. via the frontend's "Send to Coder Agent" action, which
    triggers a real Coder Agent revise() and then automatically re-runs this same route once that
    revision completes), never used to block pipeline advancement itself.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.SECURITY, "run", request.human_comment)

    try:
        output = await security_agent.run(feature_id=feature_id)

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.SECURITY,
            status="completed",
            message=output.message,
            artifact_ids=output.artifact_ids,
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("========== SECURITY AGENT ERROR ==========")
        print(traceback.format_exc())
        print("===========================================")

        raise HTTPException(
            status_code=500,
            detail=f"Security Agent failed: {_readable_error(error)}"
        )


@router.post("/security/scan-with-model", response_model=AgentRunResponse)
async def run_security_agent_deep_scan(feature_id: str, request: SecurityAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Run the Security Agent's AI-model deep-code-read scan -- a separate trigger from
    /security/run: the same 3 deterministic layers, plus a genuinely new layer that shows the
    configured model REAL generated source code directly (not just a findings summary) and asks
    it to identify vulnerabilities, each with a concrete root cause and suggested fix. Saves a new
    version of the same security_report artifact (scan_type: "ai_model_deep_scan"), so it flows
    through the exact same approval/version-history/chat machinery as a standard scan.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.SECURITY, "run", request.human_comment)

    try:
        output = await security_agent.run_ai_model_scan(feature_id=feature_id)

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.SECURITY,
            status="completed",
            message=output.message,
            artifact_ids=output.artifact_ids,
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("========== SECURITY AGENT (AI MODEL SCAN) ERROR ==========")
        print(traceback.format_exc())
        print("============================================================")

        raise HTTPException(
            status_code=500,
            detail=f"Security Agent AI-model scan failed: {_readable_error(error)}"
        )


@router.post("/security/scan-with-model/stream")
async def run_security_agent_deep_scan_stream(feature_id: str, request: SecurityAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /security/scan-with-model -- real, live progress (a percentage a human can
    watch, computed client-side from current/total) instead of one blocking response, plus a real
    stop: aborting the client's fetch cancels this generator (FastAPI/Starlette's own behavior, see
    architecture_agent's own run_stream for the same established pattern), so nothing is saved if a
    human stops the scan partway through.

    Events:
        {"type": "phase", "phase": "...", "label": "..."}
        {"type": "progress", "current": i, "total": N, "label": "..."}
        {"type": "error", "message": "..."}
        {"type": "done", "artifact_ids": [...], "message": "...", "gate_decision": "...", "findings_count": N}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.SECURITY, "run", request.human_comment)

    async def event_stream():
        try:
            async for event in security_agent.run_ai_model_scan_stream(feature_id=feature_id):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps(
                {"type": "error", "message": f"Security Agent AI-model scan failed: {_readable_error(error)}"}
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/security/chat", response_model=SecurityChatHistoryResponse)
def get_security_chat_history(feature_id: str, current_user: dict = Depends(get_current_user)):
    """Real, persisted chat history (store.security_conversations) -- reloading the page must not
    lose the conversation. Mirrors get_qa_chat_history exactly. See
    security_agent.agent.SecurityAgent.chat_stream for how turns are appended."""
    _validate_feature(feature_id, current_user)
    document = store.security_conversations.get(feature_id)
    turns = document.get("turns", []) if document else []
    return SecurityChatHistoryResponse(turns=[SecurityChatTurn(**turn) for turn in turns])


@router.post("/security/chat/stream")
async def security_chat_stream(feature_id: str, request: SecurityChatMessageRequest, current_user: dict = Depends(get_current_user)):
    """
    Real, token-by-token streaming Q&A about the feature's latest security report -- deliberately
    pure discussion, no code-editing side effects (see security_agent/prompt.py's
    SECURITY_CHAT_SYSTEM_PROMPT). Mirrors qa_chat_stream exactly: same NDJSON event shape as every
    other streaming route in this file.
    """
    _validate_feature(feature_id, current_user)

    async def event_stream():
        try:
            async for event in security_agent.chat_stream(feature_id=feature_id, message=request.message):
                yield json.dumps(event) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"Security chat failed: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/security/chat/turns/{turn_index}/edit/stream")
async def edit_security_chat_turn_stream(feature_id: str, turn_index: int, request: SecurityChatMessageRequest, current_user: dict = Depends(get_current_user)):
    """
    Direct user request: edit a past chat message and regenerate from that point forward --
    mirrors /requirement/conversation/turns/{turn_index}/edit/stream's shape, same NDJSON event
    shape as /security/chat/stream itself ({"type": "token"|"done"|"error", ...}).
    """
    _validate_feature(feature_id, current_user)

    async def event_stream():
        try:
            async for event in security_agent.edit_chat_turn_stream(
                feature_id=feature_id, turn_index=turn_index, new_message=request.message
            ):
                yield json.dumps(event) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"Failed to edit security chat turn: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


    # ----------------------------------------------------
    # QA Agent
    # ----------------------------------------------------
@router.post("/qa/run", response_model=AgentRunResponse)
async def run_qa_agent(feature_id: str, request: QAAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Run the QA Agent -- writes real Unit/Integration/Regression tests for the Coder Agent's
    generated feature, executes them for real (Jest, sandboxed), and saves a versioned report
    with per-test-case detail (target file/function, inputs, expected behavior, real status/
    failure message). Auto-approved (soft-gate), same as Security Agent's own deterministic
    layers -- a human reviews the report and can either re-run it or use the frontend's "Send
    Failing Tests to Coder Agent" action, which triggers a real Coder Agent revise() and then
    automatically re-runs this same route once that revision completes.
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.QA, "run", request.human_comment)

    try:
        output = await qa_agent.run(feature_id=feature_id)

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.QA,
            status="completed",
            message=output.message,
            artifact_ids=output.artifact_ids,
        )

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("========== QA AGENT ERROR ==========")
        print(traceback.format_exc())
        print("=====================================")

        raise HTTPException(
            status_code=500,
            detail=f"QA Agent failed: {_readable_error(error)}"
        )


@router.post("/qa/run/stream")
async def run_qa_agent_stream(feature_id: str, request: QAAgentRunRequest, current_user: dict = Depends(get_current_user)):
    """
    Streaming variant of /qa/run -- direct user request, mirrors Architecture Agent's own
    run/run_stream split (the closer template than Security's deep-scan split, since this is one
    operation gaining a streaming sibling, not a second distinct operation). Test generation is
    sequential (one real LLM call per discovered target, writing real files + needing one shared
    Jest setup before execution), unlike Security's read-only concurrent batches, so progress is
    reported per-target as generation actually proceeds:
        {"type": "phase", "phase": "discovery", "label": "..."}
        {"type": "generation_progress", "category": "unit", "target": "...", "index": i, "total": N, "label": "..."}
        {"type": "phase", "phase": "execution", "label": "..."}
        {"type": "phase", "phase": "root_cause", "label": "..."}   (only if there are failures)
        {"type": "phase", "phase": "saving", "label": "..."}
        {"type": "done", "artifact_ids": [...], "message": "...", "tests_generated": N, "tests_passed": N, "tests_failed": N}
        {"type": "error", "message": "..."}
    """
    _validate_feature(feature_id, current_user)
    stage_event_service.record(feature_id, AgentName.QA, "run", request.human_comment)

    async def event_stream():
        try:
            async for event in qa_agent.run_stream(feature_id=feature_id):
                yield json.dumps(event) + "\n"
        except ValueError as error:
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"QA Agent failed: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/qa/chat", response_model=QAChatHistoryResponse)
def get_qa_chat_history(feature_id: str, current_user: dict = Depends(get_current_user)):
    """Real, persisted chat history (store.qa_conversations) -- reloading the page must not
    lose the conversation. See qa_agent.agent.QAAgent.chat_stream for how turns are appended."""
    _validate_feature(feature_id, current_user)
    document = store.qa_conversations.get(feature_id)
    turns = document.get("turns", []) if document else []
    return QAChatHistoryResponse(turns=[QAChatTurn(**turn) for turn in turns])


@router.post("/qa/chat/stream")
async def qa_chat_stream(feature_id: str, request: QAChatMessageRequest, current_user: dict = Depends(get_current_user)):
    """
    Real, token-by-token streaming Q&A about the feature's latest QA report -- deliberately pure
    discussion, no code-editing side effects (see qa_agent/prompt.py's QA_CHAT_SYSTEM_PROMPT).
    Same NDJSON event shape as every other streaming route in this file: {"type":"token","text":
    ...} then {"type":"done","message":...}, or {"type":"error","message":...}.
    """
    _validate_feature(feature_id, current_user)

    async def event_stream():
        try:
            async for event in qa_agent.chat_stream(feature_id=feature_id, message=request.message):
                yield json.dumps(event) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"QA chat failed: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/qa/chat/turns/{turn_index}/edit/stream")
async def edit_qa_chat_turn_stream(feature_id: str, turn_index: int, request: QAChatMessageRequest, current_user: dict = Depends(get_current_user)):
    """
    Direct user request: edit a past chat message and regenerate from that point forward --
    mirrors edit_security_chat_turn_stream exactly, same NDJSON event shape as /qa/chat/stream.
    """
    _validate_feature(feature_id, current_user)

    async def event_stream():
        try:
            async for event in qa_agent.edit_chat_turn_stream(
                feature_id=feature_id, turn_index=turn_index, new_message=request.message
            ):
                yield json.dumps(event) + "\n"
        except Exception as error:
            yield json.dumps({"type": "error", "message": f"Failed to edit QA chat turn: {_readable_error(error)}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")