import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import {
  useReplyToRequirementConversationWithDocument,
  useRequirementConversation,
  useResetRequirementConversation,
  useStartRequirementConversation,
} from "./useRequirementConversation";
import {
  confirmRequirementConversationStream,
  editRequirementConversationTurnStream,
  replyToRequirementConversationStream,
  reviseRequirementStream,
} from "../api/agents";

// Everything ChatPanel needs to drive the Requirement Agent's conversational gap-filling flow
// through its own normal composer, instead of a separate bespoke UI -- state/mutations only, no
// JSX, so the chat window's actual markup lives in exactly one place (ChatPanel + ChatComposerBox
// + RequirementConversationParts).
export function useRequirementConversationFlow(featureId) {
  const { user } = useAuth();
  const [streamedText, setStreamedText] = useState("");
  const [streamStarted, setStreamStarted] = useState(false);
  const [replyStreamedText, setReplyStreamedText] = useState("");
  const [replyStreamStarted, setReplyStreamStarted] = useState(false);
  const [revisionStreamedText, setRevisionStreamedText] = useState("");
  const [revisionStreamStarted, setRevisionStreamStarted] = useState(false);
  const [editStreamedText, setEditStreamedText] = useState("");
  const [editStreamStarted, setEditStreamStarted] = useState(false);
  const queryClient = useQueryClient();

  const { data: conversation, isLoading } = useRequirementConversation(featureId);
  const start = useStartRequirementConversation(featureId);
  const respondWithDocument = useReplyToRequirementConversationWithDocument(featureId);
  const reset = useResetRequirementConversation(featureId);

  // One AbortController ref per streaming flow, created fresh at the start of each mutationFn
  // call -- lets a "Stop generating" button (direct user request, ChatGPT/Claude-style) reach
  // back into whichever stream is currently in flight. See streamNdjsonPost's own docstring for
  // why aborting here also genuinely stops the backend from generating further tokens, not just
  // the frontend from displaying them.
  const editAbortRef = useRef(null);
  const replyAbortRef = useRef(null);
  const confirmAbortRef = useRef(null);
  const reviseAbortRef = useRef(null);

  // Live, token-by-token variant of editTurn (ChatGPT/Claude-style "edit message") -- an edited
  // reply never touches the graph/artifacts/feature (only the conversation document itself
  // changes), so its "done" event's full state is written straight into the query cache instead
  // of triggering a refetch, same as respondStream below.
  const editTurnStream = useMutation({
    mutationFn: ({ turnIndex, reply }) => {
      const controller = new AbortController();
      editAbortRef.current = controller;
      return editRequirementConversationTurnStream(
        featureId,
        turnIndex,
        { reply },
        (event) => {
          if (event.type === "token") {
            setEditStreamStarted(true);
            setEditStreamedText((current) => current + event.text);
          } else if (event.type === "done") {
            queryClient.setQueryData(["requirementConversation", featureId], event.state);
          }
        },
        controller.signal
      );
    },
  });

  function handleEditTurnStream(payload) {
    setEditStreamedText("");
    setEditStreamStarted(false);
    return editTurnStream.mutateAsync(payload);
  }

  function stopEditTurnStream() {
    editAbortRef.current?.abort();
  }

  // Live, token-by-token variant of a normal typed reply (ChatGPT/Claude-style) -- the primary
  // way a human answers the agent's questions. Unlike confirmStream below, a reply never touches
  // the graph/artifacts/feature (only the conversation document itself changes), so its "done"
  // event's full state is written straight into the query cache instead of triggering a refetch
  // -- the UI updates the instant the stream finishes, no extra round trip.
  const respondStream = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      replyAbortRef.current = controller;
      return replyToRequirementConversationStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "token") {
            setReplyStreamStarted(true);
            setReplyStreamedText((current) => current + event.text);
          } else if (event.type === "done") {
            queryClient.setQueryData(["requirementConversation", featureId], event.state);
          }
        },
        controller.signal
      );
    },
  });

  function handleReplyStream(payload) {
    setReplyStreamedText("");
    setReplyStreamStarted(false);
    return respondStream.mutateAsync(payload);
  }

  function stopReplyStream() {
    replyAbortRef.current?.abort();
  }

  const confirmStream = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      confirmAbortRef.current = controller;
      return confirmRequirementConversationStream(
        featureId,
        { confirmed_by: user?.name || user?.email, ...payload },
        (event) => {
          if (event.type === "token") {
            setStreamStarted(true);
            setStreamedText((current) => current + event.text);
          }
        },
        controller.signal
      );
    },
    // Awaited (not fired-and-forgotten): mutateAsync only resolves once onSuccess resolves, and
    // the composer/chat UI clears its optimistic/live bubbles on that resolution -- if this
    // returned before the invalidated queries actually refetched, the live bubble would vanish a
    // beat before the real persisted one (from the fresh timeline) existed to replace it. Same
    // real, reproduced race as DomainAgentFlow's own invalidateAfterCompletion (see its comment).
    onSuccess: async (result) => {
      // Stopped before finishing -- nothing actually changed server-side to refetch.
      if (result?.aborted) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["requirementConversation", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["feature", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["events", featureId] }),
      ]);
    },
  });

  function handleConfirm(payload) {
    setStreamedText("");
    setStreamStarted(false);
    confirmStream.mutate(payload);
  }

  function stopConfirmStream() {
    confirmAbortRef.current?.abort();
  }

  // `confirmStream.isSuccess` alone would stay stuck true forever after a STOPPED confirm too
  // (mutateAsync resolves rather than rejects on abort, see streamNdjsonPost's own docstring) --
  // `!confirmStream.data?.aborted` is what tells "genuinely finished" apart from "was stopped
  // partway through," so stopping a confirm correctly falls back to showing the QualityGateBanner
  // again instead of an indefinite "Generating..." indicator with nothing left generating it.
  const isGenerating =
    confirmStream.isPending || (confirmStream.isSuccess && !confirmStream.data?.aborted && conversation?.status !== "confirmed");
  const isConfirmed = conversation?.status === "confirmed";

  // Live, token-by-token revision of an ALREADY-confirmed SRS (ChatGPT/Claude-style) -- distinct
  // from respondStream (the pre-confirm gap-filling conversation) and confirmStream (the initial
  // generation): this is what "ask the Requirement Agent to change something" does once a real
  // SRS artifact already exists. A revision touches real artifacts/graph status, so its onSuccess
  // invalidates the same broader query set confirmStream does, not just this hook's own state.
  const reviseStream = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      reviseAbortRef.current = controller;
      return reviseRequirementStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "token") {
            setRevisionStreamStarted(true);
            setRevisionStreamedText((current) => current + event.text);
          }
        },
        controller.signal
      );
    },
    // Awaited -- same reasoning as confirmStream's onSuccess above.
    onSuccess: async (result) => {
      if (result?.aborted) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["feature", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["events", featureId] }),
      ]);
    },
  });

  function handleReviseStream(payload) {
    setRevisionStreamedText("");
    setRevisionStreamStarted(false);
    return reviseStream.mutateAsync(payload);
  }

  function stopReviseStream() {
    reviseAbortRef.current?.abort();
  }

  return {
    conversation,
    isLoading,
    start,
    respondStream,
    handleReplyStream,
    stopReplyStream,
    replyStreamedText,
    replyStreamStarted,
    respondWithDocument,
    editTurnStream,
    handleEditTurnStream,
    stopEditTurnStream,
    editStreamedText,
    editStreamStarted,
    reset,
    confirmStream,
    handleConfirm,
    stopConfirmStream,
    streamedText,
    streamStarted,
    isGenerating,
    isConfirmed,
    reviseStream,
    handleReviseStream,
    stopReviseStream,
    revisionStreamedText,
    revisionStreamStarted,
  };
}
