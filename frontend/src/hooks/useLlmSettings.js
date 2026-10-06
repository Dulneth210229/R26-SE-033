import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getLlmSettings,
  getOllamaStatus,
  listAnthropicModels,
  listOllamaModels,
  testLlmSettings,
  updateLlmSettings,
} from "../api/llmSettings";
import {
  clearAgentLlmSettings,
  listAgentLlmSettings,
  testAgentLlmSettings,
  updateAgentLlmSettings,
} from "../api/agentLlmSettings";

export function useLlmSettings() {
  return useQuery({ queryKey: ["llmSettings"], queryFn: getLlmSettings });
}

export function useUpdateLlmSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateLlmSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llmSettings"] });
    },
  });
}

export function useTestLlmSettings() {
  return useMutation({ mutationFn: testLlmSettings });
}

// Ollama's model list rarely changes mid-session -- a generous staleTime avoids re-hitting the
// Ollama server on every chat-panel mount, and a soft failure (empty array) lets the model
// picker degrade gracefully instead of blocking the whole chat UI when Ollama isn't reachable.
export function useOllamaModels() {
  return useQuery({
    queryKey: ["ollamaModels"],
    queryFn: listOllamaModels,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

// Claude-side counterpart to useOllamaModels, same shape/reasoning -- the model dropdown
// combines both into one list (see ModelSelect.jsx), so an unreachable/unconfigured Anthropic
// account degrades to "no Claude options" rather than blocking the whole picker.
export function useAnthropicModels() {
  return useQuery({
    queryKey: ["anthropicModels"],
    queryFn: listAnthropicModels,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

// Polled while mounted -- unlike the model list, what's actually loaded into memory/VRAM
// changes as agents run (Ollama loads/unloads/evicts models on its own), so a one-shot fetch
// would go stale the moment the user watches it for more than a few seconds. `retry: false`
// matches useOllamaModels: an unreachable server is a normal, renderable state here (the backend
// reports it as `reachable: false` in a 200), not a query error to retry through.
export function useOllamaStatus() {
  return useQuery({
    queryKey: ["ollamaStatus"],
    queryFn: getOllamaStatus,
    refetchInterval: 10_000,
    retry: false,
  });
}

export function useAgentLlmSettings() {
  return useQuery({ queryKey: ["agentLlmSettings"], queryFn: listAgentLlmSettings });
}

export function useUpdateAgentLlmSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ agentName, update }) => updateAgentLlmSettings(agentName, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agentLlmSettings"] });
    },
  });
}

export function useClearAgentLlmSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (agentName) => clearAgentLlmSettings(agentName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agentLlmSettings"] });
    },
  });
}

export function useTestAgentLlmSettings() {
  return useMutation({
    mutationFn: ({ agentName, prompt }) => testAgentLlmSettings(agentName, { prompt }),
  });
}
