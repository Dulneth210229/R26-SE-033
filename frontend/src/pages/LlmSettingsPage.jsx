import { useEffect, useState } from "react";
import PageHeader from "../components/layout/PageHeader";
import LoadingSpinner from "../components/common/LoadingSpinner";
import ErrorBanner from "../components/common/ErrorBanner";
import AgentLlmOverrideRow from "../components/settings/AgentLlmOverrideRow";
import OllamaStatusCard from "../components/settings/OllamaStatusCard";
import { useAgentLlmSettings, useLlmSettings, useTestLlmSettings, useUpdateLlmSettings } from "../hooks/useLlmSettings";

export default function LlmSettingsPage() {
  const { data: settings, isLoading, error } = useLlmSettings();
  const updateSettings = useUpdateLlmSettings();
  const testSettings = useTestLlmSettings();
  const { data: agentSettings, isLoading: agentSettingsLoading, error: agentSettingsError } = useAgentLlmSettings();

  const [form, setForm] = useState(null);
  const [apiKey, setApiKey] = useState("");
  const [testPrompt, setTestPrompt] = useState("Say hello from AutoForge.");

  useEffect(() => {
    if (settings && !form) {
      setForm({
        provider: settings.provider,
        model: settings.model,
        base_url: settings.base_url,
        temperature: settings.temperature,
        max_tokens: settings.max_tokens,
        streaming_enabled: settings.streaming_enabled,
        timeout_seconds: settings.timeout_seconds,
      });
    }
  }, [settings, form]);

  if (isLoading || !form) {
    return <LoadingSpinner label="Loading LLM settings..." />;
  }

  function set(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave(event) {
    event.preventDefault();
    const update = { ...form };
    if (apiKey.trim()) {
      update.api_key = apiKey.trim();
    }
    await updateSettings.mutateAsync(update);
    setApiKey("");
  }

  return (
    <div className="h-full overflow-y-auto pr-1.5">
      <PageHeader title="LLM Settings" subtitle="Configure the provider/model used by every AutoForge agent." />

      <ErrorBanner error={error} fallback="Failed to load LLM settings." />

      <div className="bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/30 rounded-lg p-3 mb-5 text-sm text-blue-900 dark:text-blue-200">
        The settings on the left are the <strong>global default</strong> -- every agent uses it unless it
        has its own override configured below. Coder Agent in particular usually needs a model that
        supports tool-calling, which may not be the best choice for the simpler one-shot agents --
        that's what per-agent overrides are for.
      </div>

      <div className="mb-6">
        <OllamaStatusCard />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 mb-6 items-start">
        <form onSubmit={handleSave} className="flex flex-col gap-4 bg-white dark:bg-gray-900 p-5 rounded-lg shadow-sm border border-gray-200 dark:border-gray-800">
          <h3 className="text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Global Default</h3>
          <ErrorBanner error={updateSettings.error} fallback="Failed to update LLM settings." />

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Provider</label>
              <select
                value={form.provider}
                onChange={(e) => set("provider", e.target.value)}
                className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              >
                <option value="ollama">ollama</option>
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Model</label>
              <input
                value={form.model}
                onChange={(e) => set("model", e.target.value)}
                placeholder="e.g. llama3:latest"
                className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              />
            </div>
          </div>
          {form.provider === "ollama" && (
            <p className="text-xs text-gray-500 dark:text-gray-400 -mt-2">
              Must be a model already pulled locally (<code>ollama list</code>) and small enough to fit
              in this machine's GPU/VRAM, or generation can stall for many minutes.
            </p>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Base URL</label>
              <input
                value={form.base_url}
                onChange={(e) => set("base_url", e.target.value)}
                className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">
                API Key {form.provider !== "ollama" && <span className="text-red-500">*</span>}
              </label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={settings.api_key_reference ? `Current: ${settings.api_key_reference}` : "Not configured"}
                className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Temperature</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={form.temperature}
                onChange={(e) => set("temperature", parseFloat(e.target.value))}
                className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Max Tokens</label>
              <input
                type="number"
                min="1"
                value={form.max_tokens}
                onChange={(e) => set("max_tokens", parseInt(e.target.value, 10))}
                className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Timeout (s)</label>
              <input
                type="number"
                min="1"
                value={form.timeout_seconds}
                onChange={(e) => set("timeout_seconds", parseInt(e.target.value, 10))}
                className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.streaming_enabled}
              onChange={(e) => set("streaming_enabled", e.target.checked)}
            />
            Streaming enabled
          </label>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={updateSettings.isPending}
              className="self-start bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
            >
              {updateSettings.isPending ? "Saving..." : "Save Settings"}
            </button>
            {updateSettings.isSuccess && <p className="text-sm text-green-700 dark:text-green-400">Saved.</p>}
          </div>
        </form>

        <div className="bg-white dark:bg-gray-900 p-5 rounded-lg shadow-sm border border-gray-200 dark:border-gray-800 flex flex-col gap-3">
          <h3 className="text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Test Current Settings</h3>
          <ErrorBanner error={testSettings.error} fallback="Test call failed." />

          <textarea
            value={testPrompt}
            onChange={(e) => setTestPrompt(e.target.value)}
            rows={2}
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
          <button
            onClick={() => testSettings.mutate({ prompt: testPrompt })}
            disabled={testSettings.isPending}
            className="self-start bg-gray-700 hover:bg-gray-800 dark:bg-white/10 dark:hover:bg-white/20 disabled:opacity-50 text-white dark:text-gray-100 text-sm font-semibold py-1.5 px-3 rounded"
          >
            {testSettings.isPending ? "Calling model..." : "Send Test Prompt"}
          </button>

          {testSettings.data && (
            <div className="bg-gray-50 dark:bg-white/5 border border-gray-200 dark:border-gray-700 rounded p-3 text-sm text-gray-900 dark:text-gray-100">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                {testSettings.data.provider} / {testSettings.data.model}
              </p>
              <p className="whitespace-pre-wrap">{testSettings.data.output}</p>
            </div>
          )}
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 p-5 rounded-lg shadow-sm border border-gray-200 dark:border-gray-800">
        <h3 className="text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Per-Agent Overrides</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Give a specific agent its own provider/model/parameters, independent of the global default.
        </p>

        <ErrorBanner error={agentSettingsError} fallback="Failed to load per-agent settings." />

        {agentSettingsLoading ? (
          <LoadingSpinner label="Loading agent settings..." />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {agentSettings.map((agent) => (
              <AgentLlmOverrideRow key={agent.agent_name} settings={agent} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
