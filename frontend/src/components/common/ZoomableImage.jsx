import { useRef } from "react";
import { TransformWrapper, TransformComponent, useControls } from "react-zoom-pan-pinch";

// Small on-screen control cluster -- must render INSIDE <TransformWrapper> since useControls()
// needs its context. Bottom-right, semi-transparent, matching this app's existing dark-mode-aware
// button conventions -- a reviewer may not know wheel-zoom/drag-pan/double-click gestures exist.
function ZoomControls() {
  const { zoomIn, zoomOut, resetTransform } = useControls();

  return (
    <div className="absolute bottom-3 right-3 z-10 flex items-center gap-1 bg-white/90 dark:bg-gray-900/90 border border-gray-200 dark:border-gray-700 rounded-lg shadow-sm p-1">
      <button
        type="button"
        onClick={() => zoomOut()}
        title="Zoom out"
        className="w-7 h-7 flex items-center justify-center rounded text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/10 text-lg font-bold leading-none"
      >
        &minus;
      </button>
      <button
        type="button"
        onClick={() => resetTransform()}
        title="Reset zoom"
        className="w-7 h-7 flex items-center justify-center rounded text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/10 text-xs font-semibold"
      >
        1:1
      </button>
      <button
        type="button"
        onClick={() => zoomIn()}
        title="Zoom in"
        className="w-7 h-7 flex items-center justify-center rounded text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/10 text-lg font-bold leading-none"
      >
        +
      </button>
    </div>
  );
}

// Generic zoom/pan wrapper -- takes a raw `src`, not an artifact id, so it has zero coupling to
// artifact-fetching concerns and is reusable anywhere an image needs to be zoomable (e.g. the
// UI/UX Agent's page-preview screenshots later), not just Architecture diagrams.
//
// A real, confirmed bug (users "stuck," unable to reach parts of a zoomed-in diagram): the
// previous version's `contentStyle={{ width: "100%", height: "100%", ... }}` forced the
// TransformComponent's measured content box to always equal the WRAPPER's box, regardless of the
// real image's own aspect ratio -- so react-zoom-pan-pinch's pan-bounds math (based on
// `contentComponent.offsetWidth/offsetHeight`) was computed against an invisible, oversized
// padding rectangle instead of the actual rendered diagram, and `limitToBounds` hard-clamped at
// that wrong boundary. Fixed by rendering the `<img>` at its own natural size (this library's own
// documented usage pattern -- see its README example, a bare `<img>` with no sizing CSS) so the
// content box the library measures always matches the real image, then fitting it to the visible
// container ourselves via `centerView(fitScale)` once the image loads (natural size is very
// likely larger than the lightbox on at least one axis, so a plain `centerOnInit` alone would
// leave it looking "already zoomed in" on first render).
export default function ZoomableImage({ src, alt, className }) {
  const containerRef = useRef(null);
  const transformRef = useRef(null);

  function handleImageLoad(event) {
    const container = containerRef.current;
    const img = event.currentTarget;
    if (!container || !img.naturalWidth || !img.naturalHeight) return;

    const fitScale = Math.min(
      container.clientWidth / img.naturalWidth,
      container.clientHeight / img.naturalHeight,
      1
    );
    transformRef.current?.centerView(fitScale, 0);
  }

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full bg-gray-50 dark:bg-gray-950 rounded overflow-hidden ${className || ""}`}
    >
      <TransformWrapper
        ref={transformRef}
        initialScale={1}
        minScale={0.1}
        maxScale={6}
        wheel={{ step: 0.15 }}
        pinch={{ step: 5 }}
        doubleClick={{ mode: "toggle" }}
        centerZoomedOut
        limitToBounds
      >
        <ZoomControls />
        <TransformComponent wrapperStyle={{ width: "100%", height: "100%" }}>
          <img
            src={src}
            alt={alt || "Diagram"}
            draggable={false}
            onLoad={handleImageLoad}
            className="cursor-grab active:cursor-grabbing"
          />
        </TransformComponent>
      </TransformWrapper>
    </div>
  );
}
