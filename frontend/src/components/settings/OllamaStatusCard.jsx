import { useOllamaStatus } from "../../hooks/useLlmSettings";

function formatBytes(bytes) {
  if (!bytes) return "0 GB";
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function formatExpiry(expiresAt) {
  if (!expiresAt) return null;
  const diffMs = new Date(expiresAt).getTime() - Date.now();
  if (Number.isNaN(diffMs)) return null;
  if (diffMs <= 0) return "unloading soon";
  const minutes = Math.round(diffMs / 60_000);
  return minutes < 1 ? "unloading soon" : `unloads in ~${minutes}m`;
}

function RunningModelRow({ model }) {
  // Below ~60% VRAM residency, Ollama is running most of the model on CPU -- the exact,
  // previously-diagnosed cause of multi-minute agent calls on this project (see CLAUDE.md's
  // GPU/VRAM gotcha). Surfacing the threshold directly, instead of just the raw percentage,
  // is what turns this from a number into an actionable warning.
  const isMostlyCpu = model.vram_percent < 60;
  const expiry = formatExpiry(model.expires_at);

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{model.name}</p>
        <span className="text-xs text-gray-400 dark:text-gray-500 flex-shrink-0">{formatBytes(model.size_bytes)}</span>
      </div>

      <div className="mt-2 h-2 rounded-full bg-gray-100 dark:bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full ${isMostlyCpu ? "bg-amber-500" : "bg-green-500"}`}
          style={{ width: `${Math.min(model.vram_percent, 100)}%` }}
        />
      </div>

      <div className="flex items-center justify-between mt-1.5">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {model.vram_percent}% in VRAM ({formatBytes(model.size_vram_bytes)})
        </p>
        {expiry && <p className="text-xs text-gray-400 dark:text-gray-500">{expiry}</p>}
      </div>

      {isMostlyCpu && (
        <p className="text-xs text-amber-700 dark:text-amber-400 mt-1.5">
          Mostly running on CPU -- expect slow generation. Consider a smaller model.
        </p>
      )}
    </div>
  );
}

export default function OllamaStatusCard() {
  const { data: status, isLoading, error } = useOllamaStatus();

  return (
    <div className="bg-white dark:bg-gray-900 p-5 rounded-lg shadow-sm border border-gray-200 dark:border-gray-800 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Ollama Server Status</h3>
        {status && (
          <span className="flex items-center gap-1.5 text-xs font-semibold">
            <span className={`w-1.5 h-1.5 rounded-full ${status.reachable ? "bg-green-500" : "bg-red-500"}`} />
            <span className={status.reachable ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}>
              {status.reachable ? "Connected" : "Unreachable"}
            </span>
          </span>
        )}
      </div>

      {isLoading && <p className="text-sm text-gray-400 dark:text-gray-500">Checking...</p>}

      {error && (
        <p className="text-sm text-red-700 dark:text-red-400">Failed to check Ollama status.</p>
      )}

      {status && (
        <>
          <p className="text-xs text-gray-400 dark:text-gray-500 -mt-1">{status.base_url}</p>

          {!status.reachable ? (
            <p className="text-sm text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-md p-2.5">
              {status.error || "Could not connect."} Make sure Ollama is running at this address.
            </p>
          ) : (
            <>
              <div>
                <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1.5">
                  Loaded in memory ({status.running_models.length})
                </p>
                {status.running_models.length === 0 ? (
                  <p className="text-sm text-gray-400 dark:text-gray-500 italic">
                    No model currently loaded -- the next agent call will load one on demand.
                  </p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {status.running_models.map((model) => (
                      <RunningModelRow key={model.name} model={model} />
                    ))}
                  </div>
                )}
              </div>

              <p className="text-xs text-gray-400 dark:text-gray-500">
                {status.available_models.length} model{status.available_models.length === 1 ? "" : "s"} available locally
                (<code>ollama list</code>)
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}
