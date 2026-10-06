import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { editSecurityChatTurnStream, getSecurityChatHistory, securityChatStream } from "../api/agents";

// Real, persisted chat history -- reloading the page must not lose the conversation (direct
// user request). Backed by GET /security/chat (store.security_conversations). Mirrors
// useQaChatFlow.js's useQaChatHistory exactly.
export function useSecurityChatHistory(featureId) {
  return useQuery({
    queryKey: ["securityChatHistory", featureId],
    queryFn: () => getSecurityChatHistory(featureId),
    enabled: Boolean(featureId),
  });
}

// Mirrors useQaChatFlow.js's useQaChatFlow exactly (pure Q&A, no phase/tool_activity events --
// see security_agent/prompt.py's SECURITY_CHAT_SYSTEM_PROMPT), including its already-fixed
// disappearing-bubble precedent (item 49 in this project's own CLAUDE.md): the human's own
// message is held in pendingHumanMessage (not just the composer's local state, which clears on
// submit) so it stays visible for the whole in-flight duration, and onSuccess is async/awaited so
// the streamed bubbles don't unmount before the fresh, real persisted history has landed in the
// cache.
//
// editTurnStream/handleEditTurn (direct user request: edit a past message) shares the exact same
// streamed-token/pendingHumanMessage plumbing as a normal send -- the only difference is which API
// call kicks it off (editSecurityChatTurnStream instead of securityChatStream) and that the
// backend truncates history before regenerating.
export function useSecurityChatFlow(featureId) {
  const queryClient = useQueryClient();
  const [streamedText, setStreamedText] = useState("");
  const [streamStarted, setStreamStarted] = useState(false);
  const [streamError, setStreamError] = useState(null);
  const [pendingHumanMessage, setPendingHumanMessage] = useState(null);
  const abortRef = useRef(null);

  function makeOnEvent() {
    return (event) => {
      if (event.type === "token") {
        setStreamStarted(true);
        setStreamedText((current) => current + event.text);
      } else if (event.type === "error") {
        setStreamError(event.message);
      }
    };
  }

  const invalidateHistory = () => queryClient.invalidateQueries({ queryKey: ["securityChatHistory", featureId] });

  const chatStream = useMutation({
    mutationFn: (message) => {
      const controller = new AbortController();
      abortRef.current = controller;
      return securityChatStream(featureId, { message }, makeOnEvent(), controller.signal);
    },
    // The real, persisted turn (both the human's message and the full assistant reply) was
    // already appended server-side once the stream's "done" event fired -- refetch so the
    // history list picks it up instead of the app trying to reconstruct it from streamedText.
    onSuccess: invalidateHistory,
  });

  const editTurnStream = useMutation({
    mutationFn: ({ turnIndex, message }) => {
      const controller = new AbortController();
      abortRef.current = controller;
      return editSecurityChatTurnStream(featureId, turnIndex, { message }, makeOnEvent(), controller.signal);
    },
    onSuccess: invalidateHistory,
  });

  function handleSendMessage(message) {
    setStreamedText("");
    setStreamStarted(false);
    setStreamError(null);
    setPendingHumanMessage(message);
    return chatStream.mutateAsync(message).finally(() => setPendingHumanMessage(null));
  }

  function handleEditTurn(turnIndex, message) {
    setStreamedText("");
    setStreamStarted(false);
    setStreamError(null);
    setPendingHumanMessage(message);
    return editTurnStream.mutateAsync({ turnIndex, message }).finally(() => setPendingHumanMessage(null));
  }

  function stopStream() {
    abortRef.current?.abort();
  }

  return {
    chatStream, handleSendMessage, stopStream,
    editTurnStream, handleEditTurn,
    streamedText, streamStarted, streamError, pendingHumanMessage,
  };
}
