// Palette presets for the --color-accent-* CSS custom properties defined in index.css.
// Every accent-* Tailwind utility class used throughout the app (bg-accent-600, text-accent-700,
// etc.) already compiles to var(--color-accent-600) under Tailwind v4's @theme mechanism, so
// applying a preset here re-colors the whole app instantly with zero per-component changes.
export const THEME_PRESETS = {
  indigo: {
    label: "Indigo",
    swatch: "#4f46e5",
    shades: {
      50: "#eef2ff",
      100: "#e0e7ff",
      200: "#c7d2fe",
      500: "#6366f1",
      600: "#4f46e5",
      700: "#4338ca",
      800: "#3730a3",
      900: "#312e81",
    },
  },
  blue: {
    label: "Blue",
    swatch: "#2563eb",
    shades: {
      50: "#eff6ff",
      100: "#dbeafe",
      200: "#bfdbfe",
      500: "#3b82f6",
      600: "#2563eb",
      700: "#1d4ed8",
      800: "#1e40af",
      900: "#1e3a8a",
    },
  },
  emerald: {
    label: "Emerald",
    swatch: "#059669",
    shades: {
      50: "#ecfdf5",
      100: "#d1fae5",
      200: "#a7f3d0",
      500: "#10b981",
      600: "#059669",
      700: "#047857",
      800: "#065f46",
      900: "#064e3b",
    },
  },
  rose: {
    label: "Rose",
    swatch: "#e11d48",
    shades: {
      50: "#fff1f2",
      100: "#ffe4e6",
      200: "#fecdd3",
      500: "#f43f5e",
      600: "#e11d48",
      700: "#be123c",
      800: "#9f1239",
      900: "#881337",
    },
  },
  slate: {
    label: "Slate",
    swatch: "#334155",
    shades: {
      50: "#f8fafc",
      100: "#f1f5f9",
      200: "#e2e8f0",
      500: "#64748b",
      600: "#475569",
      700: "#334155",
      800: "#1e293b",
      900: "#0f172a",
    },
  },
  amber: {
    label: "Amber",
    swatch: "#d97706",
    shades: {
      50: "#fffbeb",
      100: "#fef3c7",
      200: "#fde68a",
      500: "#f59e0b",
      600: "#d97706",
      700: "#b45309",
      800: "#92400e",
      900: "#78350f",
    },
  },
};

const STORAGE_KEY = "autoforge_theme";

export function applyTheme(themeKey) {
  const preset = THEME_PRESETS[themeKey] || THEME_PRESETS.indigo;
  const root = document.documentElement;
  for (const [shade, hex] of Object.entries(preset.shades)) {
    root.style.setProperty(`--color-accent-${shade}`, hex);
  }
}

export function loadSavedTheme() {
  const saved = localStorage.getItem(STORAGE_KEY);
  return THEME_PRESETS[saved] ? saved : "indigo";
}

export function saveTheme(themeKey) {
  localStorage.setItem(STORAGE_KEY, themeKey);
}

// Light/dark color scheme -- independent of the accent color preset above. Uses a `.dark` class
// on <html> (see index.css's `@custom-variant dark`) rather than only `prefers-color-scheme`, so
// the user's explicit choice is what persists, not just whatever their OS happens to report.
const COLOR_SCHEME_KEY = "autoforge_color_scheme";

export function loadSavedColorScheme() {
  const saved = localStorage.getItem(COLOR_SCHEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyColorScheme(mode) {
  document.documentElement.classList.toggle("dark", mode === "dark");
}

export function saveColorScheme(mode) {
  localStorage.setItem(COLOR_SCHEME_KEY, mode);
}
