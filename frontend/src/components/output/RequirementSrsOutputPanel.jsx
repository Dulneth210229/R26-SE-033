import { useRequirementConversationFlowContext } from "../workspace/RequirementConversationFlowContext";
import { LiveGenerationView } from "../pipeline/RequirementConversationParts";
import { declutterJsonForDisplay } from "../../lib/streamingJsonDisplay";
import LoadingSpinner from "../common/LoadingSpinner";

// Requirement Agent, pre-SRS: the Result panel deliberately shows NOTHING SRS-shaped until real
// generation actually starts. The previous version rendered the conversation's live draft preview
// here -- mostly-defaulted placeholder content (a generic business goal, boilerplate acceptance
// criteria) that read as "here is your SRS" before the human had answered anything, per direct
// user feedback. A waiting spinner is a more honest signal that nothing real exists yet than a
// document-shaped template. Once Confirm is clicked, this becomes the primary token-by-token
// streaming view (ChatGPT/Claude-style) -- the chat panel only shows a compact pointer here
// instead of duplicating the full stream.
export default function RequirementSrsOutputPanel() {
  const { conversation, isGenerating, isConfirmed, streamedText, streamStarted } = useRequirementConversationFlowContext();

  if (isGenerating) {
    return (
      <LiveGenerationView
        displayText={declutterJsonForDisplay(streamedText)}
        hasStarted={streamStarted}
        connectingLabel="Connecting to Requirement Agent..."
        generatingLabel="Generating SRS..."
      />
    );
  }

  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 text-center py-10">
      <LoadingSpinner
        variant="cube"
        label={
          isConfirmed
            ? "Finalizing..."
            : conversation
            ? "Waiting for you to confirm and generate the SRS..."
            : "Waiting for the conversation to start..."
        }
      />
      <p className="text-xs text-gray-400 dark:text-gray-500 max-w-xs">
        The generated SRS will render here live, token by token, once you confirm in the chat panel.
      </p>
    </div>
  );
}
