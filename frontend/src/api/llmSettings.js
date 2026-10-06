import { apiClient } from "./client";

export async function getLlmSettings() {
  const { data } = await apiClient.get("/settings/llm");
  return data;
}

export async function updateLlmSettings(update) {
  const { data } = await apiClient.put("/settings/llm", update);
  return data;
}

export async function testLlmSettings({ prompt, system_prompt }) {
  const { data } = await apiClient.post("/settings/llm/test", { prompt, system_prompt });
  return data;
}

// Model names currently available on the configured Ollama server -- powers the chat
// model-picker. Only meaningful when the global/agent provider is "ollama".
export async function listOllamaModels() {
  const { data } = await apiClient.get("/settings/llm/models");
  return data.models;
}

// Model IDs currently available on the configured Anthropic account -- the Claude-side
// counterpart to listOllamaModels above, so the chat model-picker can offer real Claude models
// too, not just whichever one happens to already be selected.
export async function listAnthropicModels() {
  const { data } = await apiClient.get("/settings/llm/anthropic/models");
  return data.models;
}

// Live server status (reachability + which models are actually loaded into memory and their
// VRAM residency) -- distinct from getLlmSettings, which only reflects what's configured.
// Never throws for an unreachable server; the backend reports `reachable: false` in a normal
// 200 response instead of a 502, so this is a plain GET with no special error handling here.
export async function getOllamaStatus() {
  const { data } = await apiClient.get("/settings/llm/ollama/status");
  return data;
}
