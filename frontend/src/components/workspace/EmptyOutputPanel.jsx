const TABS = ["Result", "Files", "Preview"];

// Right-panel counterpart to EmptyChatPanel -- same tab-bar chrome as the real OutputPanel (so
// the panel doesn't just vanish/go blank before a feature exists), with pulsing skeleton bars
// standing in for "the document that will render here" instead of a stark empty box. Purely
// decorative -- there is no featureId to fetch anything for yet.
export default function EmptyOutputPanel() {
  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800">
      <div className="flex items-center border-b border-gray-100 dark:border-gray-800 flex-shrink-0 px-2">
        {TABS.map((tab) => (
          <span
            key={tab}
            className="text-sm font-semibold px-4 py-2.5 border-b-2 border-transparent text-gray-300 dark:text-gray-700 cursor-not-allowed"
          >
            {tab}
          </span>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-6 flex flex-col items-center justify-center gap-5">
        <div className="w-full max-w-sm flex flex-col gap-3 animate-pulse">
          <div className="h-3 w-1/3 bg-gray-100 dark:bg-white/10 rounded-full" />
          <div className="h-5 w-2/3 bg-gray-100 dark:bg-white/10 rounded-full" />
          <div className="h-3 w-full bg-gray-100 dark:bg-white/10 rounded-full mt-2" />
          <div className="h-3 w-5/6 bg-gray-100 dark:bg-white/10 rounded-full" />
          <div className="h-3 w-4/6 bg-gray-100 dark:bg-white/10 rounded-full" />
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500 text-center max-w-xs">
          Output will appear here once you start building your first feature.
        </p>
      </div>
    </div>
  );
}
