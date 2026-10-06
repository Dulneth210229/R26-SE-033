import { useMemo } from "react";
import StatusBadge from "../common/StatusBadge";
import ImageViewer from "../artifacts/ImageViewer";
import ApprovalPanel from "./ApprovalPanel";
import { screenshotPageLabel } from "../../lib/artifactTypeMeta";
import { featureUiuxImagesDownloadUrl } from "../../api/client";

// Direct user correction: the backend already treats every page generated together as ONE
// version (see artifact_service.save_binary_artifact's version_override fix + approval_service's
// UI/UX screenshot cascade) -- but the generic ArtifactList/ArtifactRow this replaces rendered one
// row PER PAGE'S screenshot, each with its own independent-looking Approve/Reject/Request-Revision
// buttons. For a 4-page feature that's 4 buttons that all do the exact same thing (approve the
// whole version) but read as 4 separate decisions. This component groups by version instead --
// one card per version, one approval action per pending version, a thumbnail per page within it --
// making the "a bunch of generated UIs is one version" mental model true on screen, not just in
// the database. Used ONLY for the uiux stage (see ResultTab.jsx) -- every other stage keeps the
// generic per-row ArtifactList exactly as it is today, since each row there genuinely is an
// independent decision.
export default function UiuxVersionGroupList({ artifacts, featureId, onView, onApproveClick }) {
  const groups = useMemo(() => {
    const byVersion = new Map();
    for (const artifact of artifacts) {
      if (artifact.artifact_type !== "ui_preview_screenshot") continue;
      const list = byVersion.get(artifact.version) || [];
      list.push(artifact);
      byVersion.set(artifact.version, list);
    }
    return [...byVersion.entries()]
      .sort((a, b) => b[0] - a[0])
      .map(([version, items]) => ({ version, items, status: items[0]?.approval_status }));
  }, [artifacts]);

  // Direct user request, reversing the immediately-prior session's own "free approval, no lock"
  // choice (the third time this exact lock has been added/removed on this component -- item 67
  // added it, item 68 removed it at direct user request, this now re-adds it at a NEW, separate
  // direct user request): approving a version now also starts Coder Agent automatically (see
  // ResultTab's APPROVE_CONTINUATION_BY_STAGE), so every OTHER pending version's Approve button
  // is disabled once one is approved -- mirrors ArtifactList.jsx's own approveLocked convention
  // for every other stage exactly (Reject/Request Revision stay available; ApprovalPanel's own
  // tooltip explains "reject it first" on the disabled button).
  const approvedVersion = groups.find((g) => g.status === "approved");

  if (groups.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-col gap-3 mt-3">
      <p className="text-xs text-gray-400 dark:text-gray-500">
        Approving, rejecting, or requesting revision on a version applies to its{" "}
        <strong>whole batch of pages</strong> at once -- metadata, every component, and every
        page's HTML/screenshot of that version all move together, and the shared design system is
        updated only once a version is approved.
      </p>
      {groups.map((group) => (
        <div
          key={group.version}
          className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden"
        >
          <div className="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-white/5 border-b border-gray-200 dark:border-gray-700">
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              UI/UX Output v{group.version}
              <span className="ml-2 text-xs font-normal text-gray-400 dark:text-gray-500">
                {group.items.length} page{group.items.length === 1 ? "" : "s"}
              </span>
            </span>
            <div className="flex items-center gap-3">
              {/* Direct user request: download every generated image for this version at once,
                  instead of saving each page's screenshot one by one. */}
              <a
                href={featureUiuxImagesDownloadUrl(featureId, group.version)}
                className="text-xs font-semibold text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300"
              >
                Download images (.zip)
              </a>
              <StatusBadge status={group.status} />
            </div>
          </div>

          <div className="p-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
            {group.items.map((artifact) => (
              <button
                key={artifact.artifact_id}
                type="button"
                onClick={() => onView(artifact)}
                className="text-left group"
              >
                <ImageViewer artifactId={artifact.artifact_id} boxHeight="110px" alt={screenshotPageLabel(artifact) || "Page preview"} />
                <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-1 group-hover:text-accent-600 dark:group-hover:text-accent-400">
                  {screenshotPageLabel(artifact) || "Page"}
                </p>
              </button>
            ))}
          </div>

          {group.status === "pending" && (
            <div className="px-3 pb-3">
              <ApprovalPanel
                featureId={featureId}
                artifact={group.items[0]}
                onApproveClick={
                  onApproveClick ? (comment) => onApproveClick(group.items[0].artifact_id, comment) : undefined
                }
                approveLocked={Boolean(approvedVersion) && group.version !== approvedVersion.version}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
