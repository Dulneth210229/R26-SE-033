import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";
import { useArtifactContent } from "../../hooks/useArtifacts";
import { pickViewer } from "../../lib/artifactTypeMeta";
import MarkdownViewer from "./MarkdownViewer";
import JsonViewer from "./JsonViewer";
import ImageViewer from "./ImageViewer";
import CodeViewer from "./CodeViewer";
import DiffViewer from "./DiffViewer";
import SrsDocumentViewer from "../documents/SrsDocumentViewer";
import ArchitecturePlanDocumentViewer from "../documents/ArchitecturePlanDocumentViewer";
import DomainImprovementsViewer from "../documents/DomainImprovementsViewer";
import UiMetadataViewer from "../documents/UiMetadataViewer";

// The actual viewer-format dispatch, factored out of ArtifactViewerModal so it can be reused
// both inside a popup (ArtifactViewerModal, for "View" links anywhere) and rendered directly
// inline (the per-stage Output tab) -- same content, two different containers.
//
// domainImprovementsArtifact (optional): the sibling Domain Improvements artifact for an
// Enhanced SRS, same version -- passed by ResultTab (which already looks it up to render it as
// its own attachment below) so SrsDocumentViewer can cross-reference it to highlight which
// specific SRS entries Domain Agent actually added, inline, not just listed separately. Omitted
// by ArtifactViewerModal's popup path (it doesn't have sibling-lookup context) -- the document
// still renders correctly there, just without the inline highlighting.
//
export default function ArtifactContentView({ artifact, domainImprovementsArtifact }) {
  const viewer = artifact ? pickViewer(artifact) : null;
  const { data, isLoading, error } = useArtifactContent(viewer && viewer !== "image" ? artifact?.artifact_id : null);
  const { data: domainImprovementsData } = useArtifactContent(domainImprovementsArtifact?.artifact_id ?? null);

  if (!artifact) return null;

  if (viewer === "image") return <ImageViewer artifactId={artifact.artifact_id} />;

  return (
    <>
      <ErrorBanner error={error} fallback="Failed to load artifact content." />
      {isLoading ? (
        <LoadingSpinner variant="cube" label="Loading content..." />
      ) : (
        <>
          {viewer === "diff" && <DiffViewer content={data?.content || ""} />}
          {viewer === "markdown" && <MarkdownViewer content={data?.content || ""} />}
          {viewer === "json" && <JsonViewer data={data?.content_json} />}
          {viewer === "srs-document" && (
            <SrsDocumentViewer
              data={data?.content_json}
              artifactType={artifact.artifact_type}
              domainImprovements={domainImprovementsData?.content_json}
            />
          )}
          {viewer === "architecture-document" && <ArchitecturePlanDocumentViewer data={data?.content_json} />}
          {viewer === "domain-improvements-document" && <DomainImprovementsViewer data={data?.content_json} />}
          {viewer === "ui-metadata-document" && <UiMetadataViewer data={data?.content_json} />}
          {viewer === "code" && <CodeViewer content={data?.content || ""} />}
          {viewer === "html" && <CodeViewer content={data?.content || ""} language="html" />}
          {viewer === "raw" && <pre className="text-xs whitespace-pre-wrap text-gray-800 dark:text-gray-200">{data?.content}</pre>}
        </>
      )}
    </>
  );
}
