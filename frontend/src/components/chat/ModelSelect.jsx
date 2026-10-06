import {
  useAnthropicModels,
  useOllamaModels,
  useAgentLlmSettings,
  useUpdateAgentLlmSettings,
} from "../../hooks/useLlmSettings";
import PillDropdown from "./PillDropdown";

// Model picker for the chat composer, styled as a pill next to AgentSelect (matching Cursor's
// "Grok 4.5" model selector). Important, honestly-stated constraint: no run/revise request
// schema has a per-request model field -- picking a model here actually sets that agent's
// PERSISTENT LLM override (via the existing PUT /settings/llm/agents/{agent_name} route),
// applied before the next run/revise call, not a true "just this one message" scope. The title
// attribute says so explicitly rather than implying per-message scoping that doesn't exist.
//
// Combines BOTH providers' real, live model lists into one dropdown -- Claude previously only
// ever "appeared" here by accident (whichever model happened to already be set, prepended as a
// fallback), never as a real, general choice, since this component originally only ever queried
// Ollama. Each option's value is a composite "{provider}:{model}" string (the same convention
// agentic_model_factory.py already uses internally) so PillDropdown's plain value-equality
// contract needs no changes, and picking one sends BOTH provider AND model together -- sending
// only `model` while the agent's override is still on the OTHER provider would silently persist
// a broken mismatched pair (confirmed: set_agent_override only changes fields explicitly given).
function splitCompositeModelValue(value) {
  const separatorIndex = value.indexOf(":");
  if (separatorIndex === -1) return { provider: value, model: "" };
  // An Ollama model name can itself contain a colon (e.g. "qwen3-coder:latest") -- only the
  // FIRST segment is ever the provider, everything after is rejoined as the real model name.
  return { provider: value.slice(0, separatorIndex), model: value.slice(separatorIndex + 1) };
}

export default function ModelSelect({ agentStage, fillWidth }) {
  const agentName = `${agentStage}_agent`;

  const { data: ollamaModels, isLoading: ollamaLoading, error: ollamaError } = useOllamaModels();
  const { data: anthropicModels, isLoading: anthropicLoading, error: anthropicError } = useAnthropicModels();
  const { data: agentSettings } = useAgentLlmSettings();
  const updateOverride = useUpdateAgentLlmSettings();

  const currentSetting = agentSettings?.find((a) => a.agent_name === agentName);

  // Only fully degrade to read-only text if BOTH sources failed -- one provider being briefly
  // unreachable (or simply not configured, e.g. no ANTHROPIC_API_KEY yet) shouldn't hide the
  // other's real, working options.
  if (ollamaError && anthropicError) {
    return (
      <span
        className={`text-xs text-gray-400 dark:text-gray-500 italic px-2 truncate min-w-0 block ${
          fillWidth ? "w-full" : "max-w-[140px]"
        }`}
        title="Could not load model lists from Ollama or Anthropic"
      >
        {currentSetting?.model || "model unavailable"}
      </span>
    );
  }

  const options = [
    ...(ollamaModels || []).map((model) => ({ value: `ollama:${model}`, label: model })),
    ...(anthropicModels || []).map((model) => ({ value: `anthropic:${model}`, label: `Claude: ${model}` })),
  ];

  const currentValue = currentSetting ? `${currentSetting.provider}:${currentSetting.model}` : "";
  if (currentValue && !options.some((option) => option.value === currentValue)) {
    options.unshift({ value: currentValue, label: currentSetting.model });
  }

  function handleChange(compositeValue) {
    const { provider, model } = splitCompositeModelValue(compositeValue);
    updateOverride.mutate({ agentName, update: { provider, model } });
  }

  return (
    <div className={`relative ${fillWidth ? "min-w-0" : ""}`}>
      <PillDropdown
        value={currentValue}
        options={options}
        onChange={handleChange}
        disabled={ollamaLoading || anthropicLoading || updateOverride.isPending}
        title={`Sets ${agentName}'s provider/model from now on (not just this one message)`}
        fillWidth={fillWidth}
      />
      {/* Real, confirmed bug fixed here: a rejected override (e.g. an agent not yet in
          OVERRIDABLE_AGENTS) used to fail completely silently -- the pill's own selection would
          flicker back with no explanation anywhere. Absolutely positioned (not the full-width
          ErrorBanner block) so a transient error doesn't push this composer's compact
          Agent/Model row layout around. */}
      {updateOverride.error && (
        <p className="absolute top-full left-0 mt-1 w-48 text-[11px] leading-snug text-red-600 dark:text-red-400 bg-white dark:bg-gray-900 border border-red-200 dark:border-red-500/30 rounded-md px-2 py-1 shadow-sm z-10">
          {updateOverride.error?.response?.data?.detail || updateOverride.error?.message || "Failed to change the model."}
        </p>
      )}
    </div>
  );
}
