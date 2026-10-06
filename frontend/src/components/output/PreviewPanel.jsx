import { useEffect, useState } from "react";
import { usePreviewStatus, useStartPreview, useStopPreview } from "../../hooks/usePreview";
import { useFeature } from "../../hooks/useFeatures";
import { useWorkspaceSelection } from "../workspace/WorkspaceSelectionContext";
import { slugify } from "../../lib/slugify";
import LoadingSpinner from "../common/LoadingSpinner";

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

// Cursor-style live preview of the Coder Agent's generated Next.js app --
// explicit Start/Stop only, never automatic (starting a build-and-serve
// container on every visit to this tab would be a surprising, expensive side
// effect). Status is polled while running/stale so a page refresh recovers
// "already running" state instead of looking stopped just because the
// backend's registry is in-memory (see usePreviewStatus).
export default function PreviewPanel({ featureId }) {
  const { data: status, isLoading } = usePreviewStatus(featureId);
  const { data: feature } = useFeature(featureId);
  const startPreview = useStartPreview(featureId);
  const stopPreview = useStopPreview(featureId);
  const { isPreviewExpanded, togglePreviewExpanded } = useWorkspaceSelection();
  // Bumping this remounts the iframe, forcing a fresh load -- the "real" way to refresh here:
  // status.preview_url points at a different port than the app itself, so it's cross-origin from
  // the iframe's own perspective, meaning contentWindow.location.reload() would throw. A remount
  // is the one refresh mechanism that works regardless of origin.
  const [reloadKey, setReloadKey] = useState(0);
  // Generated apps register every feature under `/{slugify(feature_name)}` (see
  // app/utils/slugify.py / the FEATURE_LINKS nav registry in the generated app/page.tsx) -- this
  // is what lets Preview open directly on THIS feature's own page instead of the generic
  // multi-feature home nav page every project's root "/" actually is.
  const featureRoute = feature?.feature_name ? `/${slugify(feature.feature_name)}` : "";
  // Tracks the route the user has actually navigated to inside the iframe, reported by the
  // generated app's PreviewRouteAnnouncer via postMessage (the iframe is cross-origin, so this
  // is the only way to know -- contentWindow.location is unreadable by browser design). Reset on
  // every reload/new preview_url back to the feature's own route (not "") so a stale path from a
  // previous session/port never lingers, and the URL bar/iframe still starts on THIS feature.
  const [currentPath, setCurrentPath] = useState(featureRoute);

  useEffect(() => {
    setCurrentPath(featureRoute);
  }, [reloadKey, status?.preview_url, featureRoute]);

  useEffect(() => {
    if (!status?.preview_url) return undefined;
    let previewOrigin;
    try {
      previewOrigin = new URL(status.preview_url).origin;
    } catch {
      return undefined;
    }
    function handleMessage(event) {
      if (event.origin !== previewOrigin) return;
      if (event.data?.type === "autoforge-preview-route" && typeof event.data.path === "string") {
        setCurrentPath(event.data.path);
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [status?.preview_url]);

  useEffect(() => {
    if (!isPreviewExpanded) return undefined;
    function handleKeyDown(event) {
      if (event.key === "Escape") togglePreviewExpanded();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isPreviewExpanded, togglePreviewExpanded]);

  if (isLoading) {
    return <LoadingSpinner variant="cube" label="Checking preview status..." />;
  }

  // Backend distinguishes WHY a start failed via detail.reason -- "unsupported_stack" (a
  // project still on the legacy MERN scaffold, which will never produce a Next.js build no
  // matter how many times the Coder Agent re-runs), "not_built" (a genuine Next.js project
  // with no successful build yet), or "conflict" (a sibling feature's preview is already
  // running). Each needs different guidance -- conflating them (e.g. telling someone on a
  // MERN project to "run the Coder Agent again") is actively wrong advice, not just vague.
  const errorDetail = startPreview.error?.response?.data?.detail;
  const reason = errorDetail && typeof errorDetail === "object" ? errorDetail.reason : null;
  const isUnsupportedStack = reason === "unsupported_stack";
  const isConflict = reason === "conflict";
  const isNotBuilt = reason === "not_built";
  const isUnknownError = startPreview.error && !isUnsupportedStack && !isConflict && !isNotBuilt;
  const isRunningOrStale = status?.status === "running" || status?.status === "stale";
  const isStale = status?.status === "stale";

  return (
    <div
      className={
        isPreviewExpanded
          ? "fixed inset-0 z-50 bg-white dark:bg-gray-900 flex flex-col gap-3 p-4"
          : "flex flex-col gap-4 h-full"
      }
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-bold text-gray-700 dark:text-gray-200">Live Preview</h3>
          {status?.status === "running" && (
            <p className="text-xs text-green-600 dark:text-green-400 font-semibold">Running</p>
          )}
          {status?.status === "stale" && (
            <p className="text-xs text-amber-600 dark:text-amber-400 font-semibold">
              Stale -- the code has changed since this preview was built. Stop and start again after
              re-running the Coder Agent.
            </p>
          )}
          {(!status || status.status === "stopped") && (
            <p className="text-xs text-gray-400 dark:text-gray-500">Not running</p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {status?.status === "running" || status?.status === "stale" ? (
            <button
              onClick={() => stopPreview.mutate()}
              disabled={stopPreview.isPending}
              className="text-sm bg-gray-700 hover:bg-gray-800 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
            >
              {stopPreview.isPending ? "Stopping..." : "Stop Preview"}
            </button>
          ) : (
            <button
              onClick={() => startPreview.mutate()}
              disabled={startPreview.isPending}
              className="text-sm bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
            >
              {startPreview.isPending ? "Starting..." : "Start Preview"}
            </button>
          )}
        </div>
      </div>

      {isRunningOrStale && (
        // A minimal, honest browser-chrome bar: a working refresh + the real URL + open-in-a-
        // real-tab + fullscreen. Deliberately no back/forward buttons -- this iframe has no real
        // navigation history to go back/forward through, and a fake pair that does nothing would
        // be worse than no buttons at all.
        <div
          className={`flex items-center gap-2 rounded-md border px-2 py-1.5 ${
            isStale
              ? "border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10"
              : "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-white/5"
          }`}
        >
          <button
            type="button"
            onClick={() => setReloadKey((k) => k + 1)}
            title="Refresh preview"
            className="text-gray-500 dark:text-gray-400 hover:text-accent-600 dark:hover:text-accent-400 flex-shrink-0"
          >
            <RefreshIcon />
          </button>
          <span
            className={`flex-1 min-w-0 truncate text-xs font-mono ${
              isStale ? "text-amber-800 dark:text-amber-300" : "text-gray-600 dark:text-gray-300"
            }`}
          >
            {status.preview_url}
            {currentPath}
          </span>
          <a
            href={`${status.preview_url}${currentPath}`}
            target="_blank"
            rel="noopener noreferrer"
            title="Open in a new tab"
            className="text-gray-500 dark:text-gray-400 hover:text-accent-600 dark:hover:text-accent-400 flex-shrink-0"
          >
            <ExternalLinkIcon />
          </a>
          <button
            type="button"
            onClick={togglePreviewExpanded}
            title={isPreviewExpanded ? "Collapse preview" : "Expand preview"}
            className="text-gray-500 dark:text-gray-400 hover:text-accent-600 dark:hover:text-accent-400 flex-shrink-0"
          >
            {isPreviewExpanded ? <CollapseIcon /> : <ExpandIcon />}
          </button>
        </div>
      )}

      {isUnsupportedStack && (
        <p className="bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300 text-sm p-3 rounded">
          {errorDetail.message}
        </p>
      )}
      {isConflict && (
        <p className="bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300 text-sm p-3 rounded">
          "{errorDetail.conflicting_feature_name}" already has a live preview running for this
          project -- stop it first, then preview this feature instead (they share the same
          working tree).
        </p>
      )}
      {isNotBuilt && (
        <p className="bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-300 text-sm p-3 rounded">
          {errorDetail.message}
        </p>
      )}
      {isUnknownError && (
        <p className="bg-red-100 dark:bg-red-500/15 text-red-700 dark:text-red-300 text-sm p-3 rounded">
          Failed to start the preview. Please try again.
        </p>
      )}

      {isRunningOrStale ? (
        <div className="flex-1 min-h-[350px] lg:min-h-[500px] border border-gray-200 dark:border-gray-800 rounded-md overflow-hidden bg-white">
          <iframe
            key={reloadKey}
            title="Live preview"
            src={`${status.preview_url}${featureRoute}`}
            className="w-full h-full min-h-[350px] lg:min-h-[500px]"
          />
        </div>
      ) : (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">
          No preview running. Click "Start Preview" to build and serve this feature's generated
          app right here.
        </p>
      )}
    </div>
  );
}
