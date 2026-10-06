import { ARTIFACT_TYPE_STAGE } from "./artifactTypeMeta";

// Extracted from StageInteractionPanel's old per-stage buildTimeline. Builds ONE agent's
// chronological feed (ask/response/decision) from the feature's full artifact/approval/event
// records -- scoped to `stage` from the start, not filtered after the fact, per direct user
// report: an earlier version of this built one combined feed across every agent and let the chat
// panel render all of it regardless of which agent was selected, so switching from Requirement to
// Domain Agent's chat still showed Requirement's own asks/responses/decisions mixed in. Each
// agent must hold only its own conversation -- switching agents switches the whole feed, not just
// which messages are highlighted. Still a real activity log, not a live back-and-forth chat -- see
// stage_event_schema.py / approval_schema.py for why these three sources can't be reconstructed
// from artifacts alone (human_comment/reviewer_comment live on separate records).
export function buildAgentTimeline(stage, allArtifacts, allApprovals, allEvents) {
  const items = [];

  for (const event of allEvents) {
    const eventStage = event.agent_name.replace(/_agent$/, "");
    if (eventStage !== stage) continue;
    items.push({
      kind: "ask",
      stage: eventStage,
      timestamp: new Date(event.requested_at).getTime(),
      comment: event.human_comment,
      eventType: event.event_type,
    });
  }

  const byVersion = new Map();
  for (const artifact of allArtifacts) {
    if (ARTIFACT_TYPE_STAGE[artifact.artifact_type] !== stage) continue;
    const key = artifact.version;
    if (!byVersion.has(key)) {
      byVersion.set(key, {
        version: artifact.version,
        timestamp: new Date(artifact.created_at).getTime(),
        types: [],
        artifactIds: [],
      });
    }
    const group = byVersion.get(key);
    group.types.push(artifact.artifact_type);
    group.artifactIds.push(artifact.artifact_id);
    // First non-empty summary wins -- when a version has a JSON+Markdown pair sharing one
    // version, only one of them typically carries a model-generated summary (e.g. CODE_PLAN's
    // own "summary" field lives on the JSON half only).
    if (!group.summary && artifact.summary) {
      group.summary = artifact.summary;
    }
  }
  for (const group of byVersion.values()) {
    items.push({
      kind: "response",
      stage,
      timestamp: group.timestamp,
      version: group.version,
      types: [...new Set(group.types)],
      summary: group.summary || null,
    });
  }

  const artifactById = new Map(allArtifacts.map((a) => [a.artifact_id, a]));
  for (const approval of allApprovals) {
    const artifact = artifactById.get(approval.artifact_id);
    if (!artifact || ARTIFACT_TYPE_STAGE[artifact.artifact_type] !== stage) continue;
    items.push({
      kind: "decision",
      stage,
      timestamp: new Date(approval.approved_at).getTime(),
      status: approval.status,
      comment: approval.reviewer_comment,
    });
  }

  items.sort((a, b) => a.timestamp - b.timestamp);
  return items;
}
