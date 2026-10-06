import Modal from "./Modal";
import ErrorBanner from "./ErrorBanner";

const TONE_BUTTON_CLASSES = {
  danger: "bg-red-600 hover:bg-red-700",
  primary: "bg-accent-600 hover:bg-accent-700",
};

// Generic "are you sure?" popup -- wraps the existing Modal so every confirmation in the app
// (deleting an unapproved artifact version, approving an SRS and starting Domain Agent, ...)
// looks and behaves the same, instead of each caller inventing its own inline confirm/cancel
// affordance. `tone="danger"` (default) is red, for destructive actions; `tone="primary"` is the
// accent color, for a confirmation that's just a "this has a real side effect, are you sure"
// pause rather than a warning against data loss. `children`, when provided (currently only the
// UI/UX-approval popup's optional MongoDB URI field, see ResultTab.jsx), renders extra
// interactive content between the message and the error banner -- every other caller simply
// omits it. `confirmDisabled` additionally disables Confirm beyond the existing `confirming`
// state, for a caller that needs to block confirming on invalid `children` input (e.g. a
// malformed URI) without a full loading state.
export default function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title = "Are you sure?",
  message,
  children,
  confirmLabel = "Confirm",
  confirmingLabel = "Working...",
  cancelLabel = "Cancel",
  confirming = false,
  confirmDisabled = false,
  error = null,
  errorFallback = "Something went wrong.",
  tone = "danger",
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="flex flex-col gap-4">
        {message && <p className="text-sm text-gray-600 dark:text-gray-300">{message}</p>}
        {children}
        <ErrorBanner error={error} fallback={errorFallback} />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={confirming}
            className="text-sm font-semibold text-gray-600 dark:text-gray-300 hover:text-gray-800 dark:hover:text-gray-100 disabled:opacity-50 py-1.5 px-3 rounded"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirming || confirmDisabled}
            className={`${TONE_BUTTON_CLASSES[tone] || TONE_BUTTON_CLASSES.danger} disabled:opacity-50 text-white text-sm font-semibold py-1.5 px-3 rounded`}
          >
            {confirming ? confirmingLabel : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}
