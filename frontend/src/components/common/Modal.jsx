import { useEffect } from "react";
import { createPortal } from "react-dom";

const WIDTH_CLASSES = {
  default: "max-w-lg",
  wide: "max-w-4xl",
  xl: "max-w-6xl",
};

export default function Modal({ open, onClose, title, children, wide = false, size, bodyClassName }) {
  useEffect(() => {
    if (!open) return;

    function handleKeyDown(event) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  // Portaled to document.body -- rendering inline would let an ancestor's CSS `transform`
  // (e.g. ProjectCard's `hover:-translate-y-1`) silently turn this `fixed inset-0` overlay into
  // one scoped to that ancestor's box instead of the real viewport (a `transform` on any
  // ancestor creates a new containing block for `position: fixed` descendants -- confirmed as a
  // real bug this way, not just a hypothetical). A portal makes the overlay's positioning
  // independent of wherever <Modal> happens to be mounted in the component tree.
  return createPortal(
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`bg-white dark:bg-gray-900 rounded-lg shadow-xl w-full ${WIDTH_CLASSES[size] || (wide ? WIDTH_CLASSES.wide : WIDTH_CLASSES.default)} max-h-[90vh] flex flex-col`}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300 text-xl leading-none"
            aria-label="Close"
          >
            &times;
          </button>
        </div>
        <div className={`px-6 py-4 text-gray-700 dark:text-gray-300 ${bodyClassName || "overflow-y-auto"}`}>{children}</div>
      </div>
    </div>,
    document.body
  );
}
