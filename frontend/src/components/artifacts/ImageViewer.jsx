import { artifactContentUrl } from "../../api/client";

// `boxHeight` renders the image inside a fixed-height, centered box (object-contain) instead of
// its own natural size -- used anywhere multiple images of varying real dimensions must appear
// visually consistent (e.g. switching between Use Case/Sequence/Class diagram tabs, which are
// rarely the same aspect ratio or size).
export default function ImageViewer({ artifactId, alt, boxHeight }) {
  if (boxHeight) {
    return (
      <div
        className="w-full bg-gray-50 rounded border border-gray-200 dark:border-gray-700 flex items-center justify-center overflow-hidden"
        style={{ height: boxHeight }}
      >
        <img
          src={artifactContentUrl(artifactId)}
          alt={alt || "Artifact preview"}
          className="max-w-full max-h-full object-contain"
        />
      </div>
    );
  }

  return (
    <img src={artifactContentUrl(artifactId)} alt={alt || "Artifact preview"} className="max-w-full rounded border border-gray-200" />
  );
}
