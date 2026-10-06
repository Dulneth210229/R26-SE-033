import { useEffect, useRef, useState } from "react";
import {
  applyColorScheme,
  applyTheme,
  loadSavedColorScheme,
  loadSavedTheme,
  saveColorScheme,
  saveTheme,
  THEME_PRESETS,
} from "../../lib/theme";

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-4 h-4">
      <circle cx="12" cy="12" r="4" />
      <path
        strokeLinecap="round"
        d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

export default function ThemeSwitcher() {
  const [current, setCurrent] = useState(loadSavedTheme());
  const [colorScheme, setColorScheme] = useState(loadSavedColorScheme());
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    applyTheme(current);
  }, [current]);

  useEffect(() => {
    applyColorScheme(colorScheme);
  }, [colorScheme]);

  useEffect(() => {
    function handleClickOutside(event) {
      if (ref.current && !ref.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function choose(themeKey) {
    setCurrent(themeKey);
    saveTheme(themeKey);
    setOpen(false);
  }

  function toggleColorScheme() {
    const next = colorScheme === "dark" ? "light" : "dark";
    setColorScheme(next);
    saveColorScheme(next);
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={toggleColorScheme}
        title={colorScheme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        className="w-7 h-7 rounded-full flex items-center justify-center text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
      >
        {colorScheme === "dark" ? <MoonIcon /> : <SunIcon />}
      </button>

      <div className="relative" ref={ref}>
        <button
          onClick={() => setOpen((v) => !v)}
          title="Change color theme"
          className="w-7 h-7 rounded-full border-2 border-white dark:border-gray-900 shadow ring-1 ring-gray-200 dark:ring-gray-700"
          style={{ backgroundColor: THEME_PRESETS[current].swatch }}
        />
        {open && (
          <div className="absolute right-0 mt-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-2 z-20 w-40">
            <p className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide px-1 pb-1">
              Theme
            </p>
            <div className="flex flex-col gap-0.5">
              {Object.entries(THEME_PRESETS).map(([key, preset]) => (
                <button
                  key={key}
                  onClick={() => choose(key)}
                  className="flex items-center gap-2 px-1.5 py-1.5 rounded hover:bg-gray-50 dark:hover:bg-gray-700 text-sm text-gray-700 dark:text-gray-200"
                >
                  <span className="w-4 h-4 rounded-full flex-shrink-0" style={{ backgroundColor: preset.swatch }} />
                  {preset.label}
                  {key === current && <span className="ml-auto text-xs text-gray-400 dark:text-gray-500">&#10003;</span>}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
