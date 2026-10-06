import { useId } from "react";

// The "Light Horse" loader from https://uiverse.io/RiccardoRapelli/light-horse-54 -- direct user
// request, shown ONLY in chat windows while waiting for an agent to start responding (after a
// message is sent, before the first token/response arrives). Reproduces the original markup
// exactly, with three adaptations:
// 1. Theme-aware color instead of the original's hardcoded blue/purple gradient -- same
//    convention already established by index.css's own .cube-loader (colored purely via
//    var(--color-accent-*), never a hardcoded hex) so this automatically tracks the user's chosen
//    accent preset (theme.js's applyTheme) with no new wiring.
// 2. A unique SVG filter id per instance (via useId) -- the original hardcodes id="gooey"; two
//    instances on the same page at once would collide and break the url(#gooey) reference for one
//    of them.
// 3. Scaled down for inline chat use via a CSS transform on a wrapper div around the otherwise-
//    untouched 180px layout, rather than hand-recomputing every keyframe/position value for a
//    smaller size. The scale must live on its OWN element, not on `.light-horse-loading-content`
//    itself -- that element's own `light-horse-rotate` keyframes also animate `transform`, and a
//    CSS animation replaces an element's entire computed `transform` for the properties it
//    defines, silently discarding any inline `transform: scale(...)` set on the same element (a
//    real bug caught live: the loader rendered as an empty box, since the un-scaled 180px content
//    only rarely swept through the 56px clipped viewport). Confirmed fixed by live verification.
// 4. No `overflow: hidden` on the outer box -- a second real, reported bug: each 50px "liquid"
//    blob is deliberately centered ON the 180px content box's own edges (top/left: 0%/100%),
//    so by design roughly HALF of every blob overshoots beyond that box at any given moment --
//    that's what makes the shapes visually merge into one gooey blob via the SVG filter below,
//    rather than reading as 4 separate circles. An outer wrapper sized exactly to the loader's
//    own footprint with `overflow: hidden` clips off that entire intentional overshoot, which is
//    exactly what a real, live measurement confirmed: up to ~46% of a blob's own diameter cut off
//    at several points in every rotation. Left as `overflow: visible` (the default) -- the real
//    overshoot at this component's actual sizes (max ~5px at size=40) stays well within the
//    gap-2/gap-3 spacing every real call site already places next to it.
export default function LightHorseLoader({ size = 56 }) {
  const rawId = useId();
  const filterId = `light-horse-gooey-${rawId.replace(/[^a-zA-Z0-9]/g, "")}`;
  const scale = size / 180;

  return (
    <div style={{ width: size, height: size, position: "relative" }}>
      <div style={{ width: 180, height: 180, transform: `scale(${scale})`, transformOrigin: "top left" }}>
        <div className="light-horse-loading-content" style={{ filter: `url(#${filterId})` }}>
          <div className="light-horse-liquid" />
          <div className="light-horse-liquid" />
          <div className="light-horse-liquid" />
          <div className="light-horse-liquid" />
        </div>
      </div>
      <svg width="0" height="0" style={{ position: "absolute" }}>
        <filter id={filterId}>
          <feGaussianBlur stdDeviation="10" in="SourceGraphic" />
          <feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -10" />
        </filter>
      </svg>
    </div>
  );
}
