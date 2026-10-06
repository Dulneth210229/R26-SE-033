import axios from "axios";
import { apiClient, API_BASE_URL } from "./client";
import { getToken } from "../lib/authToken";

const base = (featureId) => `/features/${featureId}/agents`;

// Shared by every streamed endpoint (confirm, reply): POSTs a JSON body and reads the response
// body as newline-delimited JSON events via fetch's own ReadableStream reader (not axios, which
// buffers the whole response) -- onEvent is called once per parsed line, in order, as it arrives.
//
// `signal`, when provided, lets a caller stop an in-flight stream -- direct user request for a
// ChatGPT/Claude-style "stop generating" control. Aborting mid-`fetch` or mid-`reader.read()` both
// throw a DOMException named "AbortError"; that's treated as a normal (non-error) stop rather than
// a failure, so the UI doesn't show a spurious "Request failed" banner for something the human
// asked for. FastAPI/Starlette's StreamingResponse cancels its underlying async generator when it
// detects the client disconnected, so this genuinely stops the backend from generating further
// tokens too, not just from the frontend showing them.
async function streamNdjsonPost(url, body, onEvent, signal) {
  let response;
  const token = getToken();
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") return { aborted: true };
    throw error;
  }

  if (!response.ok || !response.body) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    let read;
    try {
      read = await reader.read();
    } catch (error) {
      if (error.name === "AbortError") return { aborted: true };
      throw error;
    }
    const { done, value } = read;
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let newlineIndex;
    while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (!line) continue;

      try {
        onEvent(JSON.parse(line));
      } catch {
        // Malformed/partial line -- ignore rather than crash the whole stream.
      }
    }
  }

  return { aborted: false };
}

// Shared by every non-streaming run/revise call (Domain/Architecture/UIUX/Coder): a plain
// await-the-full-response POST, but still cancelable via `signal` for the same "stop generating"
// control the streaming endpoints get -- these agents don't type token-by-token, so there's no
// partial output to stop mid-flow, but the human can still stop WAITING on it (composer re-enables
// immediately) instead of being stuck watching a spinner for whatever's left of the LLM call.
// Unlike the streaming case, a plain `await agent.run(...)` on the backend may not itself be
// interrupted by the client disconnecting (depends on how that particular call is structured) --
// this is honestly a "stop watching," not a guaranteed "stop the agent" for these four agents.
async function postCancelable(url, body, signal) {
  try {
    const { data } = await apiClient.post(url, body, { signal });
    return data;
  } catch (error) {
    if (axios.isCancel(error)) return { aborted: true };
    throw error;
  }
}

// Requirement Agent
export async function runRequirement(featureId, { ba_input, human_comment }, signal) {
  return postCancelable(`${base(featureId)}/requirement/run`, { ba_input, human_comment }, signal);
}

// Live, token-by-token revision (ChatGPT/Claude-style) -- the agent's revision_summary reaction
// + the regenerated SRS "type" in as they're generated, same mechanism as the other streamed
// Requirement Agent endpoints. This is the only revise path the frontend uses now; the backend's
// plain (non-streaming) POST /requirement/revise route still exists and works for any direct API
// caller, it's just no longer called from here.
export async function reviseRequirementStream(featureId, { revision_comment, revised_by }, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/requirement/revise/stream`,
    { revision_comment, revised_by },
    onEvent,
    signal
  );
}

// Requirement Agent conversational gap-filling loop -- additive, alongside run/revise above.
export async function startRequirementConversation(featureId) {
  const { data } = await apiClient.post(`${base(featureId)}/requirement/conversation/start`);
  return data;
}

// Live, token-by-token reply (ChatGPT/Claude-style) -- the agent's reaction+questions "type" in
// as they're generated, same newline-delimited-JSON-over-fetch mechanism as
// confirmRequirementConversationStream below. This is the only reply path the frontend uses now;
// the backend's plain (non-streaming) POST /requirement/conversation/reply route still exists and
// works for any direct API caller, it's just no longer called from here.
export async function replyToRequirementConversationStream(featureId, { reply }, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/requirement/conversation/reply/stream`,
    { reply },
    onEvent,
    signal
  );
}

// Reply with an attached text/PDF/DOCX/MD document -- the backend extracts its full text and
// scrapes requirements from it the same way it would from typed text. Omitting an explicit
// Content-Type lets the browser/axios set the multipart boundary itself; setting it manually
// would break the upload.
export async function replyToRequirementConversationWithDocument(featureId, { file, reply }, signal) {
  const formData = new FormData();
  formData.append("file", file);
  if (reply) formData.append("reply", reply);
  return postCancelable(`${base(featureId)}/requirement/conversation/reply/upload`, formData, signal);
}

// Edits an already-submitted reply and regenerates the conversation from that point forward --
// mirrors ChatGPT/Claude's "edit message" flow. Discards the edited turn and everything after it.
// Live, token-by-token: the regenerated reaction+questions "type" in live instead of sitting
// behind a plain spinner for however long the real LLM call takes, same mechanism as
// replyToRequirementConversationStream. The backend also still has a plain (non-streaming) POST
// .../turns/{turnIndex}/edit route for any direct API caller; the frontend only uses this one.
export async function editRequirementConversationTurnStream(featureId, turnIndex, { reply }, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/requirement/conversation/turns/${turnIndex}/edit/stream`,
    { reply },
    onEvent,
    signal
  );
}

export async function getRequirementConversation(featureId) {
  const { data } = await apiClient.get(`${base(featureId)}/requirement/conversation`);
  return data;
}

export async function resetRequirementConversation(featureId) {
  const { data } = await apiClient.post(`${base(featureId)}/requirement/conversation/reset`);
  return data;
}

export async function confirmRequirementConversation(
  featureId,
  { override_quality_gate = false, override_reason, confirmed_by = "human_user" } = {}
) {
  const { data } = await apiClient.post(`${base(featureId)}/requirement/conversation/confirm`, {
    override_quality_gate,
    override_reason,
    confirmed_by,
  });
  return data;
}

// Streaming variant -- the response body is newline-delimited JSON events
// ({"type": "token"|"error"|"done", ...}) so the SRS can be shown "typing" live as it's
// generated. onEvent is called once per parsed line, in order.
export async function confirmRequirementConversationStream(
  featureId,
  { override_quality_gate = false, override_reason, confirmed_by = "human_user" } = {},
  onEvent,
  signal
) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/requirement/conversation/confirm/stream`,
    { override_quality_gate, override_reason, confirmed_by },
    onEvent,
    signal
  );
}

// Domain Agent (auto-runs via the graph once Requirement is approved; both a manual initial run
// and revise are also real, e.g. for referencing an uploaded document via "/" before the graph
// gets there on its own)
export async function runDomain(featureId, { human_comment, referenced_document_ids = [] } = {}, signal) {
  return postCancelable(`${base(featureId)}/domain/run`, { human_comment, referenced_document_ids }, signal);
}

export async function reviseDomain(
  featureId,
  { revision_comment, revised_by, referenced_document_ids = [] },
  signal
) {
  return postCancelable(
    `${base(featureId)}/domain/revise`,
    { revision_comment, revised_by, referenced_document_ids },
    signal
  );
}

// Live, token-by-token variants (ChatGPT/Claude-style) -- same newline-delimited-JSON-over-fetch
// mechanism as Requirement Agent's streaming endpoints. Direct user report: Domain Agent's chat
// was the one agent left on a blocking-wait-then-sudden-reveal experience (composer stayed
// disabled with the typed text still sitting in it until the whole enrichment finished, no live
// output, no way to stop) while Requirement Agent already had all of that. These are what
// DomainAgentChat/useDomainAgentFlow use instead of the plain runDomain/reviseDomain above.
export async function runDomainStream(
  featureId,
  { human_comment, referenced_document_ids = [] } = {},
  onEvent,
  signal
) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/domain/run/stream`,
    { human_comment, referenced_document_ids },
    onEvent,
    signal
  );
}

export async function reviseDomainStream(
  featureId,
  { revision_comment, revised_by, referenced_document_ids = [] },
  onEvent,
  signal
) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/domain/revise/stream`,
    { revision_comment, revised_by, referenced_document_ids },
    onEvent,
    signal
  );
}

// Architecture Agent
export async function runArchitecture(
  featureId,
  { use_enhanced_srs_if_available = true, architecture_notes, human_comment },
  signal
) {
  return postCancelable(
    `${base(featureId)}/architecture/run`,
    { use_enhanced_srs_if_available, architecture_notes, human_comment },
    signal
  );
}

export async function reviseArchitecture(featureId, { revision_comment, revised_by }, signal) {
  return postCancelable(`${base(featureId)}/architecture/revise`, { revision_comment, revised_by }, signal);
}

// Live, token-by-token variants (ChatGPT/Claude-style), same mechanism as Domain Agent's
// runDomainStream/reviseDomainStream above -- what ArchitectureAgentChat/useArchitectureAgentFlow
// use instead of the plain runArchitecture/reviseArchitecture. Events additionally include a
// "phase" type (see the backend routes' own docstrings) for the non-streamable tail (use case
// model, diagram generation, PlantUML rendering) once the plan text itself finishes streaming.
export async function runArchitectureStream(
  featureId,
  { use_enhanced_srs_if_available = true, architecture_notes, human_comment } = {},
  onEvent,
  signal
) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/architecture/run/stream`,
    { use_enhanced_srs_if_available, architecture_notes, human_comment },
    onEvent,
    signal
  );
}

export async function reviseArchitectureStream(featureId, { revision_comment, revised_by }, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/architecture/revise/stream`,
    { revision_comment, revised_by },
    onEvent,
    signal
  );
}

// UI/UX Agent
export async function runUiux(
  featureId,
  { use_enhanced_srs_if_available = true, ui_preferences, human_comment } = {},
  signal
) {
  return postCancelable(
    `${base(featureId)}/uiux/run`,
    { use_enhanced_srs_if_available, ui_preferences, human_comment },
    signal
  );
}

export async function reviseUiux(featureId, { revision_comment, revised_by, target_page_ids }, signal) {
  return postCancelable(`${base(featureId)}/uiux/revise`, { revision_comment, revised_by, target_page_ids }, signal);
}

// Live, token-by-token variants (ChatGPT/Claude-style), same mechanism as Domain/Architecture
// Agent's run*Stream/revise*Stream above -- what UiuxAgentChat/useUiuxAgentFlow use instead of the
// plain runUiux/reviseUiux. Events additionally include a "phase" type for the non-streamable tail
// (component generation, page assembly/rendering) once ui_metadata_json itself finishes
// streaming -- see the backend routes' own docstrings.
export async function runUiuxStream(
  featureId,
  { use_enhanced_srs_if_available = true, ui_preferences, human_comment } = {},
  onEvent,
  signal
) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/uiux/run/stream`,
    { use_enhanced_srs_if_available, ui_preferences, human_comment },
    onEvent,
    signal
  );
}

export async function reviseUiuxStream(featureId, { revision_comment, revised_by, target_page_ids }, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/uiux/revise/stream`,
    { revision_comment, revised_by, target_page_ids },
    onEvent,
    signal
  );
}

// Coder Agent
export async function runCoder(
  featureId,
  { use_enhanced_srs_if_available = true, human_comment } = {},
  signal
) {
  return postCancelable(`${base(featureId)}/coder/run`, { use_enhanced_srs_if_available, human_comment }, signal);
}

export async function reviseCoder(featureId, { revision_comment, revised_by }, signal) {
  return postCancelable(`${base(featureId)}/coder/revise`, { revision_comment, revised_by }, signal);
}

// Live, streaming variants (ChatGPT/Claude-style), same mechanism as Domain/Architecture Agent's
// run*Stream/revise*Stream above -- what CoderAgentChat/useCoderAgentFlow use instead of the
// plain runCoder/reviseCoder. Events additionally include a "phase" type for the non-streamable
// coding/verify tail (coding_loop.py's agentic loop has no token-level streaming at all) once the
// plan text itself finishes streaming/exploring -- see the backend routes' own docstrings. The
// "done" event also carries verification_passed/status, unlike Domain/Architecture's uniform
// "done, success" framing, since a Coder Agent run can finish with verification failures.
export async function runCoderStream(
  featureId,
  { use_enhanced_srs_if_available = true, human_comment } = {},
  onEvent,
  signal
) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/coder/run/stream`,
    { use_enhanced_srs_if_available, human_comment },
    onEvent,
    signal
  );
}

export async function reviseCoderStream(featureId, { revision_comment, revised_by }, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/coder/revise/stream`,
    { revision_comment, revised_by },
    onEvent,
    signal
  );
}

// Security Agent -- the standard run has no revise/streaming variant (see security_schema.py's
// own docstring: a re-run IS the whole operation), but chat DOES stream, live Q&A about the latest
// report -- same "run vs. chat" split as QA Agent below. The AI-model deep scan below DOES have a
// streaming variant (real per-batch progress), kept alongside its own non-streaming route per this
// project's own "old non-streaming route stays" precedent.
export async function runSecurity(featureId, { human_comment } = {}, signal) {
  return postCancelable(`${base(featureId)}/security/run`, { human_comment }, signal);
}

// A separate trigger from runSecurity above -- runs the AI-model deep-code-read scan instead of
// the standard deterministic+summary-review scan. Saves a new version of the same security_report
// artifact (report.scan_type distinguishes which kind of scan produced it). Non-streaming; kept
// for direct API callers, but the UI now uses runSecurityDeepScanStream below for live progress.
export async function runSecurityDeepScan(featureId, { human_comment } = {}, signal) {
  return postCancelable(`${base(featureId)}/security/scan-with-model`, { human_comment }, signal);
}

// Live-progress variant of runSecurityDeepScan -- real per-batch "phase"/"progress" NDJSON events
// (see agent.py's run_ai_model_scan_stream), so a human watching sees a real, growing percentage
// instead of a bare "Scanning..." label, and can genuinely stop it mid-scan via `signal`.
export async function runSecurityDeepScanStream(featureId, { human_comment } = {}, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/security/scan-with-model/stream`, { human_comment }, onEvent, signal
  );
}

export async function getSecurityChatHistory(featureId) {
  const { data } = await apiClient.get(`${base(featureId)}/security/chat`);
  return data;
}

export async function securityChatStream(featureId, { message }, onEvent, signal) {
  return streamNdjsonPost(`${API_BASE_URL}${base(featureId)}/security/chat/stream`, { message }, onEvent, signal);
}

// Direct user request: edit a past chat message and regenerate from that point forward -- same
// NDJSON shape as securityChatStream itself.
export async function editSecurityChatTurnStream(featureId, turnIndex, { message }, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/security/chat/turns/${turnIndex}/edit/stream`, { message }, onEvent, signal
  );
}

// QA Agent -- plain, blocking run (real LLM calls + a real sandboxed test run). Kept alongside
// runQaStream below (mirrors every other agent's own plain-route-stays-alongside-streaming-route
// precedent) though the frontend now exclusively uses the streaming variant to trigger a run --
// see useQaRunStream.js's own docstring.
export async function runQa(featureId, { human_comment } = {}, signal) {
  return postCancelable(`${base(featureId)}/qa/run`, { human_comment }, signal);
}

// Live-progress variant of runQa -- direct user request, mirrors runSecurityDeepScanStream's own
// shape. Real per-target "generation_progress" NDJSON events plus phase events for
// discovery/execution/root-cause-analysis/saving (see agent.py's run_stream), so a human watching
// sees real, live progress instead of a bare blank wait for the whole run.
export async function runQaStream(featureId, { human_comment } = {}, onEvent, signal) {
  return streamNdjsonPost(`${API_BASE_URL}${base(featureId)}/qa/run/stream`, { human_comment }, onEvent, signal);
}

export async function getQaChatHistory(featureId) {
  const { data } = await apiClient.get(`${base(featureId)}/qa/chat`);
  return data;
}

export async function qaChatStream(featureId, { message }, onEvent, signal) {
  return streamNdjsonPost(`${API_BASE_URL}${base(featureId)}/qa/chat/stream`, { message }, onEvent, signal);
}

// Direct user request: edit a past chat message and regenerate from that point forward -- same
// NDJSON shape as qaChatStream itself.
export async function editQaChatTurnStream(featureId, turnIndex, { message }, onEvent, signal) {
  return streamNdjsonPost(
    `${API_BASE_URL}${base(featureId)}/qa/chat/turns/${turnIndex}/edit/stream`, { message }, onEvent, signal
  );
}
