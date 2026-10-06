"""
Stage event service.

Records each human-initiated run()/revise() request so the frontend can render a real
chronological "ask" timeline per stage -- see stage_event_schema.py for the full rationale.
"""

from datetime import datetime

from app.core.enums import AgentName
from app.schemas.stage_event_schema import StageEventResponse
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id
from app.utils.logger import get_logger

logger = get_logger(__name__)


class StageEventService:
    def record(
        self,
        feature_id: str,
        agent_name: AgentName,
        event_type: str,
        human_comment: str | None,
        requested_by: str = "human_user",
    ) -> StageEventResponse | None:
        """
        Record one run()/revise() request. Never raises -- a failure to log this purely
        informational timeline event should never block the real agent call it's paired with.
        Returns None (and logs) on failure instead.
        """
        event = {
            "event_id": generate_id("event"),
            "feature_id": feature_id,
            "agent_name": agent_name,
            "event_type": event_type,
            "human_comment": human_comment,
            "requested_by": requested_by,
            "requested_at": datetime.utcnow(),
        }

        # Feature.updated_at was previously dead data (set once at creation, never bumped) --
        # this is the one real choke point every run/revise/clarify/confirm across every stage
        # funnels through, so it's the natural place to make it a real "last activity" signal,
        # powering "open a project -> default to whichever feature was worked on most recently"
        # (mirrors routes/projects.py's own existing project["updated_at"] = ... pattern).
        feature = store.features.get(feature_id)
        if feature:
            feature["updated_at"] = event["requested_at"]

        try:
            store.stage_events[event["event_id"]] = event
            return StageEventResponse(**event)
        except Exception:
            logger.exception("Failed to record stage event for feature_id=%s", feature_id)
            return None

    def list_feature_events(self, feature_id: str) -> list[StageEventResponse]:
        """
        Return every recorded run()/revise() request for a feature, oldest first.
        """
        results = []

        for event in store.stage_events.values():
            if event.get("feature_id") != feature_id:
                continue

            try:
                results.append(StageEventResponse(**event))
            except Exception:
                logger.warning("Skipping unparseable stage event %s", event.get("event_id"))

        results.sort(key=lambda e: e.requested_at)
        return results


stage_event_service = StageEventService()
