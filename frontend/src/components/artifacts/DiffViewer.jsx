import { useEffect, useMemo, useRef, useState } from "react";
import { Diff2HtmlUI } from "diff2html/lib-esm/ui/js/diff2html-ui-base.js";
import "diff2html/bundles/css/diff2html.min.css";
import MarkdownViewer from "./MarkdownViewer";

const MAX_DIFF_TEXT_CHARS = 20_000; // mirrors diff_builder.py's own truncation cap

// The code_diff artifact is a single markdown "merge report" (see diff_builder.py's
// build_merge_report_markdown): everything above "## Detailed Code Changes (Line-by-Line Diff)"
// is normal prose (verification status, steps, files changed); the diff itself is a fenced
// ```diff block at the end.
function splitMergeReport(markdown) {
  const match = markdown.match(/```diff\n([\s\S]*?)```/);

  if (!match) {
    return { prose: markdown, diffText: null };
  }

  const diffStart = markdown.indexOf(match[0]);
  return { prose: markdown.slice(0, diffStart), diffText: match[1] };
}

// Uses the real interactive Diff2HtmlUI class (not diff2html's static html() string API +
// dangerouslySetInnerHTML, which this used to do) for two reasons, both real bugs: (1) diff2html's
// own CSS makes its line-number gutter cells `position: absolute` with no positioned ancestor
// anywhere in this app's tree -- with no containing block, those cells escaped to the page's root
// and inflated the WHOLE dashboard's scroll height instead of staying inside this panel (the
// `relative` class on the container below is the actual fix -- it gives those cells something to
// anchor to); (2) the static API never wires up the per-file collapse/hide-show controls diff2html
// itself renders into the markup -- they were always inert, unclickable HTML. Diff2HtmlUI's own
// `fileContentToggle` config wires those up for real.
export default function DiffViewer({ content }) {
  const { prose, diffText } = useMemo(() => splitMergeReport(content), [content]);
  const containerRef = useRef(null);
  const [renderFailed, setRenderFailed] = useState(false);

  useEffect(() => {
    if (!diffText || !containerRef.current) return;

    try {
      new Diff2HtmlUI(containerRef.current, diffText, {
        drawFileList: true,
        matching: "lines",
        outputFormat: "line-by-line",
        // No hljs instance is bundled (the "-base" variant deliberately excludes highlight.js to
        // avoid a real bundle-size cost) -- matches this viewer's pre-existing behavior, which
        // never highlighted syntax either.
        highlight: false,
        // The actual fix for per-file expand/collapse: wires up click handlers on the
        // hide/show controls diff2html already renders into the markup.
        fileContentToggle: true,
      }).draw();
      setRenderFailed(false);
    } catch {
      setRenderFailed(true);
    }
  }, [diffText]);

  const isTruncated = diffText && diffText.length >= MAX_DIFF_TEXT_CHARS;
  const showFallbackMessage = !diffText || renderFailed;

  return (
    <div>
      <MarkdownViewer content={prose} />

      {isTruncated && (
        <p className="bg-yellow-50 dark:bg-yellow-500/10 text-yellow-800 dark:text-yellow-300 text-xs p-2 rounded mt-2 mb-2">
          This diff was truncated by the backend at {MAX_DIFF_TEXT_CHARS.toLocaleString()} characters
          -- the full diff is not available via this view.
        </p>
      )}

      {diffText && (
        // diff2html's own bundled CSS renders a light-themed table regardless of app theme --
        // wrapped in a light card so it stays legible rather than half-blending into a dark page.
        // `text-gray-900` is load-bearing, not decorative -- this div otherwise sets no color of
        // its own and inherits the app's dark-mode ancestor text color (near-white), which only
        // diff2html's own explicitly-colored elements (e.g. `.d2h-file-name` links) escape --
        // everything else (the "Files changed (N)"/"hide"/"show" file-list chrome, plain
        // whitespace/text nodes) rendered white text on this div's own white background,
        // confirmed via a real computed-style check: `color: rgb(255,255,255)` on a
        // `background-color: rgb(255,255,255)` box. Forcing a dark text color here, independent
        // of theme, is what actually makes "always render light" (the comment below) true.
        // `relative` is load-bearing too (see this file's own docstring above), not decorative --
        // without it, diff2html's absolutely-positioned line-number gutter cells escape this box
        // entirely. `max-h-[70vh] overflow-y-auto` (alongside the pre-existing overflow-x-auto)
        // keeps a large diff scrolling locally instead of dominating the whole Result tab.
        <div
          ref={containerRef}
          className={`mt-4 text-xs bg-white text-gray-900 rounded-lg p-2 relative max-h-[70vh] overflow-y-auto overflow-x-auto ${
            renderFailed ? "hidden" : ""
          }`}
        />
      )}

      {showFallbackMessage && (
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-4">No diff content found in this artifact.</p>
      )}
    </div>
  );
}
