import { apiClient } from "./client";

export async function listAgentLlmSettings() {
  const { data } = await apiClient.get("/settings/llm/agents");
  return data;
}

export async function updateAgentLlmSettings(agentName, update) {
  const { data } = await apiClient.put(`/settings/llm/agents/${agentName}`, update);
  return data;
}

export async function clearAgentLlmSettings(agentName) {
  const { data } = await apiClient.delete(`/settings/llm/agents/${agentName}`);
  return data;
}

export async function testAgentLlmSettings(agentName, { prompt, system_prompt }) {
  const { data } = await apiClient.post(`/settings/llm/agents/${agentName}/test`, { prompt, system_prompt });
  return data;
}
