import { useEffect, useRef, useState } from "react";

// A custom-built dropdown, not a native <select> -- a native select's popup menu is rendered by
// the OS/browser itself and can't be given rounded corners, a shadow, or a selected-item
// highlight from CSS, which is exactly what looked dated about the previous AgentSelect/
// ModelSelect pills. This renders its own absolutely-positioned menu instead, so it can look like
// every other rounded surface in this app. Opens upward (`bottom-full`) since both current call
// sites live in the composer bar near the bottom of their panel, where a downward menu would run
// off the panel/viewport edge.
export default function PillDropdown({
  value,
  options,
  onChange,
  disabled,
  leading,
  title,
  emptyLabel = "...",
  // A max-width default, not baked into the base class string -- a caller passing its own
  // max-w-* class here is the ONLY max-w class ever present for that instance (Tailwind's
  // generated-CSS order for two equal-specificity utility classes is not reliably predictable
  // from JSX string position alone, so appending an override string after a hardcoded one is not
  // a safe way to let a caller widen/narrow the trigger).
  triggerClassName = "max-w-[160px]",
  menuClassName = "",
  scrollable = true,
  // "up" (default) matches this component's original two call sites, both living near the
  // bottom of their panel (the composer bar) where a downward menu would run off the viewport.
  // "down" is for a trigger near the TOP of its panel instead (e.g. a Result tab's version
  // picker) -- only the popup's own positioning classes change, everything else is identical.
  direction = "up",
  // Direct, real bug fix: the composer's Agent/Model pills only ever had an upper bound
  // (triggerClassName's max-w-*), never anything letting them actually SHRINK when the row runs
  // out of room -- at narrow (laptop-width) columns the trigger kept its full intrinsic content
  // width and visibly overflowed past the composer's own card border. `fillWidth` makes both the
  // root wrapper and the trigger button real, shrinkable flex participants (w-full + min-w-0) so
  // the row's normal flex-shrink behavior can squeeze this pill down to its max-w-* cap AND
  // below it once space is genuinely tight, letting the label's own `truncate` take over instead
  // of overflowing. Defaults to false so VersionSelect (which wants intrinsic/max-content sizing,
  // not full-width stretch) is completely unaffected.
  fillWidth = false,
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!open) return;

    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  const selected = options.find((option) => option.value === value);

  return (
    <div ref={containerRef} className={`relative inline-flex ${fillWidth ? "w-full min-w-0" : ""}`}>
      <button
        type="button"
        disabled={disabled}
        title={title}
        onClick={() => setOpen((current) => !current)}
        className={`inline-flex items-center gap-1.5 text-xs font-medium rounded-full bg-white dark:bg-white/10 border border-gray-300 dark:border-transparent text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed pl-3 pr-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-accent-500 cursor-pointer ${fillWidth ? "w-full min-w-0" : ""} ${triggerClassName}`}
      >
        {leading}
        <span className="truncate min-w-0">{selected?.label ?? emptyLabel}</span>
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className={`w-3 h-3 flex-shrink-0 text-gray-400 dark:text-gray-500 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {open && (
        <div
          className={`absolute ${direction === "down" ? "top-full mt-2" : "bottom-full mb-2"} left-0 min-w-[190px] ${
            scrollable ? "max-h-64 overflow-y-auto" : ""
          } rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg ring-1 ring-black/5 dark:ring-white/10 py-1 z-20 ${menuClassName}`}
        >
          {options.map((option) => {
            const isSelected = option.value === value;
            return (
              <button
                key={option.value}
                type="button"
                disabled={option.disabled}
                onClick={() => {
                  if (option.disabled) return;
                  onChange(option.value);
                  setOpen(false);
                }}
                className={`w-full flex items-center justify-between gap-2 text-left text-sm px-3 py-1.5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                  isSelected
                    ? "bg-accent-50 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300 font-semibold"
                    : "text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/5"
                }`}
              >
                <span className="truncate">{option.label}</span>
                {isSelected && (
                  <svg viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5 flex-shrink-0">
                    <path
                      fillRule="evenodd"
                      d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
                      clipRule="evenodd"
                    />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
