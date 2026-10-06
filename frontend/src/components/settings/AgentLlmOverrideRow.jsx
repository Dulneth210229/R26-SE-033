import { useState } from "react";
import {
  useClearAgentLlmSettings,
  useTestAgentLlmSettings,
  useUpdateAgentLlmSettings,
} from "../../hooks/useLlmSettings";
import ErrorBanner from "../common/ErrorBanner";

const STAGE_LABELS = {
  requirement_agent: "Requirement Agent",
  domain_agent: "Domain Agent",
  architecture_agent: "Architecture Agent",
  uiux_agent: "UI/UX Agent",
  coder_agent: "Coder Agent",
};

export default function AgentLlmOverrideRow({ settings }) {
  const [expanded, setExpanded] = useState(false);
  const [form, setForm] = useState({
    provider: settings.provider,
    model: settings.model,
    temperature: settings.temperature,
    max_tokens: settings.max_tokens,
    timeout_seconds: settings.timeout_seconds,
  });
  const [testPrompt, setTestPrompt] = useState("Say hello from AutoForge.");

  const update = useUpdateAgentLlmSettings();
  const clear = useClearAgentLlmSettings();
  const test = useTestAgentLlmSettings();

  function set(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave(event) {
    event.preventDefault();
    await update.mutateAsync({ agentName: settings.agent_name, update: form });
  }

  async function handleReset() {
    await clear.mutateAsync(settings.agent_name);
    setExpanded(false);
  }

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg">
      <div className="flex items-center justify-between p-3">
        <div>
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{STAGE_LABELS[settings.agent_name] || settings.agent_name}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {settings.provider} / {settings.model}
            {settings.is_override ? (
              <span className="ml-2 bg-accent-100 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300 px-1.5 py-0.5 rounded text-xs font-semibold">
                Custom override
              </span>
            ) : (
              <span className="ml-2 text-gray-400 dark:text-gray-500">using global default</span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          {settings.is_override && (
            <button onClick={handleReset} disabled={clear.isPending} className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 font-semibold">
              Reset to default
            </button>
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold"
          >
            {expanded ? "Close" : "Configure"}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-100 dark:border-gray-800 p-3">
          <form onSubmit={handleSave} className="flex flex-col gap-3">
            <ErrorBanner error={update.error} fallback="Failed to update." />

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold mb-1 text-gray-900 dark:text-gray-200">Provider</label>
                <select
                  value={form.provider}
                  onChange={(e) => set("provider", e.target.value)}
                  className="w-full p-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
                >
                  <option value="ollama">ollama</option>
                  <option value="openai">openai</option>
                  <option value="anthropic">anthropic</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1 text-gray-900 dark:text-gray-200">Model</label>
                <input
                  value={form.model}
                  onChange={(e) => set("model", e.target.value)}
                  className="w-full p-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1 text-gray-900 dark:text-gray-200">Temperature</label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={form.temperature}
                  onChange={(e) => set("temperature", parseFloat(e.target.value))}
                  className="w-full p-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1 text-gray-900 dark:text-gray-200">Max Tokens</label>
                <input
                  type="number"
                  min="1"
                  value={form.max_tokens}
                  onChange={(e) => set("max_tokens", parseInt(e.target.value, 10))}
                  className="w-full p-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={update.isPending}
              className="self-start bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white text-sm font-semibold py-1.5 px-3 rounded"
            >
              {update.isPending ? "Saving..." : "Save Override"}
            </button>
          </form>

          <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
            <ErrorBanner error={test.error} fallback="Test call failed." />
            <div className="flex gap-2">
              <input
                value={testPrompt}
                onChange={(e) => setTestPrompt(e.target.value)}
                className="flex-1 p-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              />
              <button
                onClick={() => test.mutate({ agentName: settings.agent_name, prompt: testPrompt })}
                disabled={test.isPending}
                className="bg-gray-700 hover:bg-gray-800 dark:bg-white/10 dark:hover:bg-white/20 disabled:opacity-50 text-white dark:text-gray-100 text-xs font-semibold px-3 rounded"
              >
                {test.isPending ? "Testing..." : "Test"}
              </button>
            </div>
            {test.data && (
              <p className="text-xs text-gray-600 dark:text-gray-300 mt-2 bg-gray-50 dark:bg-white/5 rounded p-2 whitespace-pre-wrap">{test.data.output}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
