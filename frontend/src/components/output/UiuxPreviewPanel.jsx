import { useEffect, useMemo, useState } from "react";
import { useFeatureArtifacts, useArtifactContent } from "../../hooks/useArtifacts";
import { useWorkspaceSelection } from "../workspace/WorkspaceSelectionContext";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

function RefreshIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
      <path
        fillRule="evenodd"
        d="M15.312 5.312a5.5 5.5 0 00-9.201 2.466.75.75 0 11-1.454-.372A7 7 0 0117.5 8.973V6.75a.75.75 0 011.5 0v4a.75.75 0 01-.75.75h-4a.75.75 0 010-1.5h1.845a5.484 5.484 0 00-.783-4.688zM3.75 9.5a.75.75 0 01.75.75v1.845a5.484 5.484 0 009.201 2.093.75.75 0 111.454.372A7 7 0 012.5 11.027V13.25a.75.75 0 01-1.5 0v-4a.75.75 0 01.75-.75h1z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
      <path d="M11 3a1 1 0 100 2h2.586L8.293 10.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z" />
      <path d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z" />
    </svg>
  );
}

function ExpandIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
      <path d="M13 3a1 1 0 100 2h1.586l-3.293 3.293a1 1 0 001.414 1.414L16 6.414V8a1 1 0 102 0V3h-5z" />
      <path d="M7 17a1 1 0 100-2H5.414l3.293-3.293a1 1 0 00-1.414-1.414L4 13.586V12a1 1 0 10-2 0v5h5z" />
    </svg>
  );
}

function CollapseIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
      <path d="M13.5 9a1 1 0 01-1-1V4.5a1 1 0 112 0V6.586l3.293-3.293a1 1 0 111.414 1.414L15.914 8H18a1 1 0 010 2h-4.5z" />
      <path d="M6.5 11a1 1 0 011 1v3.5a1 1 0 11-2 0V13.414l-3.293 3.293a1 1 0 01-1.414-1.414L4.086 12H2a1 1 0 010-2h4.5z" />
    </svg>
  );
}

// Real, confirmed bug this fixes: the previous "dedupe by the file's own basename" logic assumed
// a page's filename was stable across versions -- but _save_artifacts actually writes
// "{feature_slug}_{page_slug}_page_v{version}.html", embedding the version IN the name, so every
// version of every page has a distinct basename and nothing ever actually collapsed. This showed
// every page ever generated across every historical version, growing forever, instead of just the
// current one. Fixed to filter by the real version NUMBER: only the single highest version
// present is shown, per direct user correction ("only the new version must appear").
function latestPageArtifacts(artifacts) {
  const matches = artifacts.filter((a) => a.artifact_type === "ui_page_html");
  if (matches.length === 0) return [];

  const latestVersion = Math.max(...matches.map((a) => a.version));
  return matches
    .filter((a) => a.version === latestVersion)
    .sort((a, b) => a.file_path.localeCompare(b.file_path));
}

function pageDisplayName(artifact) {
  // "{feature_slug}_{page_slug}_page_v{version}.html" -> a readable page label. Best-effort --
  // falls back to the raw filename if the naming convention ever changes.
  const base = artifact.file_path.split(/[\\/]/).pop().replace(/\.html$/i, "");
  const match = base.match(/^(.*)_page_v\d+$/);
  const slug = match ? match[1] : base;
  return slug.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function openHtmlInNewTab(html) {
  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// Static-HTML counterpart to PreviewPanel.jsx (the Coder Agent's Docker-backed live preview) --
// deliberately NOT the same mechanism. A UI/UX page is a self-contained HTML+Tailwind document
// with no server/data-fetching/build step of its own, so a browser can render it directly via
// <iframe srcDoc> with zero container/port/staleness machinery -- instant, and sidesteps this
// agent's own historically flaky Playwright/render pipeline entirely for the primary preview.
export default function UiuxPreviewPanel({ featureId }) {
  const { data: artifacts, isLoading: artifactsLoading } = useFeatureArtifacts(featureId);
  const { isPreviewExpanded, togglePreviewExpanded } = useWorkspaceSelection();
  const [selectedArtifactId, setSelectedArtifactId] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  const pages = useMemo(() => latestPageArtifacts(artifacts || []), [artifacts]);

  useEffect(() => {
    if (pages.length === 0) {
      setSelectedArtifactId(null);
      return;
    }
    if (!pages.some((p) => p.artifact_id === selectedArtifactId)) {
      setSelectedArtifactId(pages[0].artifact_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages]);

  const { data: content, isLoading: contentLoading, error } = useArtifactContent(selectedArtifactId);

  useEffect(() => {
    if (!isPreviewExpanded) return undefined;
    function handleKeyDown(event) {
      if (event.key === "Escape") togglePreviewExpanded();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isPreviewExpanded, togglePreviewExpanded]);

  if (artifactsLoading) {
    return <LoadingSpinner variant="cube" label="Loading page designs..." />;
  }

  if (pages.length === 0) {
    return (
      <p className="text-sm text-gray-400 dark:text-gray-500 italic">
        No page designs yet -- run the UI/UX Agent to generate an HTML + Tailwind design for this
        feature, then preview it here.
      </p>
    );
  }

  const selectedPage = pages.find((p) => p.artifact_id === selectedArtifactId) || pages[0];
  const html = content?.content || "";

  return (
    <div
      className={
        isPreviewExpanded
          ? "fixed inset-0 z-50 bg-white dark:bg-gray-900 flex flex-col gap-3 p-4"
          : "flex flex-col gap-3 h-full"
      }
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-sm font-bold text-gray-700 dark:text-gray-200">Page Design Preview</h3>

        {pages.length > 1 && (
          <div className="flex items-center gap-1 overflow-x-auto">
            {pages.map((page) => (
              <button
                key={page.artifact_id}
                onClick={() => setSelectedArtifactId(page.artifact_id)}
                className={`text-xs font-semibold px-2.5 py-1 rounded-md whitespace-nowrap ${
                  page.artifact_id === selectedPage.artifact_id
                    ? "bg-accent-600 text-white"
                    : "bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-white/20"
                }`}
              >
                {pageDisplayName(page)}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-white/5 px-2 py-1.5">
        <button
          type="button"
          onClick={() => setReloadKey((k) => k + 1)}
          title="Refresh preview"
          className="text-gray-500 dark:text-gray-400 hover:text-accent-600 dark:hover:text-accent-400 flex-shrink-0"
        >
          <RefreshIcon />
        </button>
        <span className="flex-1 min-w-0 truncate text-xs font-mono text-gray-600 dark:text-gray-300">
          {pageDisplayName(selectedPage)} (v{selectedPage.version})
        </span>
        <button
          type="button"
          onClick={() => html && openHtmlInNewTab(html)}
          disabled={!html}
          title="Open in a new tab"
          className="text-gray-500 dark:text-gray-400 hover:text-accent-600 dark:hover:text-accent-400 flex-shrink-0 disabled:opacity-40"
        >
          <ExternalLinkIcon />
        </button>
        <button
          type="button"
          onClick={togglePreviewExpanded}
          title={isPreviewExpanded ? "Collapse preview" : "Expand preview"}
          className="text-gray-500 dark:text-gray-400 hover:text-accent-600 dark:hover:text-accent-400 flex-shrink-0"
        >
          {isPreviewExpanded ? <CollapseIcon /> : <ExpandIcon />}
        </button>
      </div>

      <ErrorBanner error={error} fallback="Failed to load the page design." />

      <div className="flex-1 min-h-[500px] border border-gray-200 dark:border-gray-800 rounded-md overflow-hidden bg-white">
        {contentLoading ? (
          <LoadingSpinner variant="cube" label="Loading page design..." />
        ) : (
          <iframe
            key={`${selectedPage.artifact_id}-${reloadKey}`}
            title="Page design preview"
            srcDoc={html}
            // A bare srcDoc iframe resolves relative hrefs (e.g. "#") against the PARENT page's
            // own URL, not the srcdoc content -- clicking a link could otherwise navigate this
            // iframe to the AutoForge app itself, rendering it nested inside the preview (a real,
            // confirmed bug). page_html_builder.py's inline click-guard script is the primary
            // fix; this sandbox is defense-in-depth -- allow-scripts only (needed for the inlined
            // Tailwind CDN script), deliberately no allow-same-origin/allow-top-navigation/
            // allow-popups/allow-forms, so no navigation/popup/same-origin attempt can succeed
            // regardless of what a future generation contains.
            sandbox="allow-scripts"
            className="w-full h-full min-h-[500px]"
          />
        )}
      </div>
    </div>
  );
}
