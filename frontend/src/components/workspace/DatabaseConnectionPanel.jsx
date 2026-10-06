import { useState } from "react";
import {
  useDatabaseConnection,
  useDeleteDatabaseConnection,
  useSaveDatabaseConnection,
} from "../../hooks/useDatabaseConnection";
import { looksLikeMongoUri } from "../../lib/mongoUri";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

// Per-project MongoDB connection string: the standalone entry point (mirrors
// DomainKnowledgePanel.jsx's shape), independent of any specific Coder Agent run -- the other
// entry point is the optional field shown in the UI/UX-approval popup right before Coder Agent
// starts (see ResultTab.jsx), and a third, pre-existing path (typing/pasting a URI directly into
// the Coder Agent chat) already worked before this panel existed. All three write through the
// same backend `.env.local`, so any one of them is immediately visible to the others.
export default function DatabaseConnectionPanel({ projectId }) {
  const { data, isLoading, error } = useDatabaseConnection(projectId);
  const save = useSaveDatabaseConnection(projectId);
  const remove = useDeleteDatabaseConnection(projectId);
  const [draft, setDraft] = useState("");

  const draftIsValid = draft.trim().length === 0 || looksLikeMongoUri(draft);

  function handleSave() {
    if (!looksLikeMongoUri(draft)) return;
    save.mutate(draft.trim(), { onSuccess: () => setDraft("") });
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-gray-500 dark:text-gray-400">
        Save a real MongoDB connection string here and every generated route that already has the
        built-in "serve seed data until a real database is configured" fallback automatically
        starts serving real data instead -- no code regeneration needed.
      </p>

      <ErrorBanner error={error} fallback="Failed to load the database connection status." />

      {isLoading ? (
        <LoadingSpinner label="Loading..." />
      ) : (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-4">
          {data?.configured ? (
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-green-700 dark:text-green-400 uppercase tracking-wide">
                  Configured
                </p>
                <p className="text-sm text-gray-700 dark:text-gray-300 font-mono truncate mt-0.5" title={data.masked_uri}>
                  {data.masked_uri}
                </p>
              </div>
              <button
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
                className="text-sm text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400 font-semibold flex-shrink-0"
              >
                {remove.isPending ? "Clearing..." : "Clear"}
              </button>
            </div>
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500 italic">Not configured yet -- generated apps serve seed data.</p>
          )}
        </div>
      )}

      <ErrorBanner error={save.error} fallback="Failed to save the connection string." />
      <ErrorBanner error={remove.error} fallback="Failed to clear the connection string." />

      <div>
        <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">
          {data?.configured ? "Replace with a new connection string" : "MongoDB connection string"}
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="mongodb+srv://user:password@cluster0.xxx.mongodb.net/mydb"
            className="flex-1 min-w-0 px-3 py-2 text-sm font-mono border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
          <button
            onClick={handleSave}
            disabled={save.isPending || draft.trim().length === 0 || !draftIsValid}
            className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded flex-shrink-0"
          >
            {save.isPending ? "Saving..." : "Save"}
          </button>
        </div>
        {!draftIsValid && (
          <p className="text-xs text-red-600 dark:text-red-400 mt-1">
            Must start with mongodb:// or mongodb+srv://
          </p>
        )}
      </div>
    </div>
  );
}
