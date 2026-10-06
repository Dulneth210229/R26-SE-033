import { useRef } from "react";
import { useKnowledgeDocuments, useUploadKnowledgeDocument, useDeleteKnowledgeDocument } from "../../hooks/useKnowledgeDocuments";
import { knowledgeDocumentDownloadUrl } from "../../api/knowledge";
import StatusBadge from "../common/StatusBadge";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

function formatBytes(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Reuses StatusBadge's approved/rejected color styling (green/red) for ready/failed, but with
// document-appropriate label text -- a knowledge document was never "approved," it was just
// processed successfully.
const STATUS_MAP = { processing: "processing", ready: "approved", failed: "rejected" };
const STATUS_LABEL = { processing: "Processing...", ready: "Ready", failed: "Failed" };

// Per-project domain knowledge management: upload PDF/DOCX/TXT/MD files here, then reference one
// by typing "/" in the chat composer while talking to the Domain Agent -- every chunk of a
// referenced document is guaranteed context, not just whatever similarity search surfaces.
export default function DomainKnowledgePanel({ projectId }) {
  const { data, isLoading, error } = useKnowledgeDocuments(projectId);
  const documents = data || [];
  const upload = useUploadKnowledgeDocument(projectId);
  const remove = useDeleteKnowledgeDocument(projectId);
  const fileInputRef = useRef(null);

  function handleFileChange(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) upload.mutate(file);
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-gray-500 dark:text-gray-400">
        Upload a database schema, style guide, business rules doc, or any other reference
        material for this project. Reference a specific document by typing <code>/</code> in the
        chat while talking to the Domain Agent.
      </p>

      <div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          onChange={handleFileChange}
          className="hidden"
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={upload.isPending}
          className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
        >
          {upload.isPending ? "Uploading..." : "+ Upload Document"}
        </button>
        <ErrorBanner error={upload.error} fallback="Failed to upload document." />
      </div>

      <ErrorBanner error={error} fallback="Failed to load knowledge documents." />

      {isLoading ? (
        <LoadingSpinner label="Loading documents..." />
      ) : documents.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">
          No domain knowledge documents uploaded yet.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {documents.map((doc) => (
            <div
              key={doc.document_id}
              className="flex items-center justify-between flex-wrap gap-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate" title={doc.original_filename}>
                  {doc.original_filename}
                </p>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                  {formatBytes(doc.file_size_bytes)}
                  {doc.status === "ready" && ` · ${doc.chunk_count} chunk${doc.chunk_count === 1 ? "" : "s"}`}
                  {doc.status === "failed" && doc.failure_reason ? ` · ${doc.failure_reason}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <StatusBadge
                  status={STATUS_MAP[doc.status] || doc.status}
                  label={STATUS_LABEL[doc.status]}
                />
                <a
                  href={knowledgeDocumentDownloadUrl(projectId, doc.document_id)}
                  className="text-sm text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold"
                >
                  Download
                </a>
                <button
                  onClick={() => remove.mutate(doc.document_id)}
                  disabled={remove.isPending}
                  className="text-sm text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400 font-semibold"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
