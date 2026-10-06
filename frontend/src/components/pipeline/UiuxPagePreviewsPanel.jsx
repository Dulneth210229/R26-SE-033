import { artifactDownloadUrl } from "../../api/client";
import ImageViewer from "../artifacts/ImageViewer";

// Real, confirmed bug this fixes: the previous "dedupe by the file's own basename" logic assumed
// a page's filename was stable across versions -- but _save_artifacts actually writes
// "{feature_slug}_{page_slug}_v{version}.png", embedding the version IN the name, so every
// version of every page has a distinct basename and nothing ever actually collapsed. This showed
// every screenshot ever generated across every historical version, growing forever, instead of
// just the current one. Fixed to filter by the real version NUMBER: only the single highest
// version present is shown, per direct user correction ("only the new version must appear").
function latestByFile(artifacts) {
  const matches = artifacts.filter((a) => a.artifact_type === "ui_preview_screenshot");
  if (matches.length === 0) return [];

  const latestVersion = Math.max(...matches.map((a) => a.version));
  return matches.filter((a) => a.version === latestVersion);
}

// This is the UI/UX stage's MAIN output, not a side extra -- per direct user feedback, a human
// reviewing this stage cares most about what the pages actually look like, not the raw
// ui_metadata JSON. Rendered full-width with real-size screenshots; the metadata/components live
// in the narrower side column instead (see StageOutputPanel).
export default function UiuxPagePreviewsPanel({ allArtifacts }) {
  const screenshots = latestByFile(allArtifacts);

  if (screenshots.length === 0) {
    return <p className="text-sm text-gray-400 dark:text-gray-500 italic">No page previews were rendered for this stage.</p>;
  }

  return (
    <div>
      <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-3">
        Page Previews ({screenshots.length})
      </h3>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {screenshots.map((artifact) => (
          <div key={artifact.artifact_id} className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-white/5 border-b border-gray-200 dark:border-gray-700">
              <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 truncate" title={artifact.file_path}>
                {artifact.file_path.split(/[\\/]/).pop()}
              </p>
              <a
                href={artifactDownloadUrl(artifact.artifact_id)}
                className="text-xs text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold flex-shrink-0"
              >
                Download
              </a>
            </div>
            <div className="p-2">
              <ImageViewer artifactId={artifact.artifact_id} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
