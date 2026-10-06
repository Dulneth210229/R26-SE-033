import { STAGE_LABELS, SELECTABLE_AGENT_STAGES } from "../../lib/pipelineStages";
import { useWorkspaceSelection } from "../workspace/WorkspaceSelectionContext";
import PillDropdown from "./PillDropdown";

// Agent picker for the chat composer, styled as a rounded pill (matching Cursor's "Agent"
// selector in the composer bar). Every real agent stage is listed; a stage strictly AHEAD of
// the pipeline's current reachable point (see WorkspaceSelectionContext's own currentStage,
// computed via lib/deriveCurrentStage.js) is disabled -- direct user request: while still on,
// say, the Coder Agent stage, a human should not be able to jump straight to Security/QA's chat
// until the Coder Agent's own output is approved and the pipeline actually advances. Stages at
// or before the current one stay freely selectable, so revisiting an earlier agent's chat
// history is never blocked -- only forward-jumping past the frontier is. `isRunning` renders a
// small pulsing dot so the currently-selected agent's live/processing state is visible right on
// the pill itself.
//
// QA gets one additional, content-aware exception on top of the stage-order gate above: Security
// is a soft/auto-approved gate, so the stage-order check alone would let a human reach QA the
// moment ANY security report exists, regardless of findings. Direct user request: QA must stay
// unreachable while the latest security scan still has Critical findings (see
// WorkspaceSelectionContext's own securityGateBlocksQa for how that's computed).
export default function AgentSelect({ value, onChange, isRunning, fillWidth }) {
  const { currentStage, securityGateBlocksQa } = useWorkspaceSelection();
  const currentStageIndex = SELECTABLE_AGENT_STAGES.indexOf(currentStage);

  const options = SELECTABLE_AGENT_STAGES.map((stage, index) => ({
    value: stage,
    label: STAGE_LABELS[stage],
    disabled:
      (currentStageIndex !== -1 && index > currentStageIndex) || (stage === "qa" && securityGateBlocksQa),
  }));

  const leading = isRunning ? (
    <span className="relative flex h-1.5 w-1.5 flex-shrink-0">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent-500" />
    </span>
  ) : null;

  return (
    <PillDropdown
      value={value}
      options={options}
      onChange={onChange}
      title="Select which agent to talk to"
      leading={leading}
      scrollable={false}
      fillWidth={fillWidth}
    />
  );
}
