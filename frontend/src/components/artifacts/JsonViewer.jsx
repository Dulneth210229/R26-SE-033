import { useEffect, useState } from "react";
import { JsonView, allExpanded, darkStyles, defaultStyles } from "react-json-view-lite";
import "react-json-view-lite/dist/index.css";

// react-json-view-lite ships its own light/dark style objects (not Tailwind classes) -- picking
// between them requires knowing the current color scheme in JS, so this watches the same `.dark`
// class ThemeSwitcher toggles on <html> rather than duplicating that state.
function useIsDark() {
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains("dark"));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return isDark;
}

export default function JsonViewer({ data }) {
  const isDark = useIsDark();

  if (data == null) {
    return <p className="text-gray-500 dark:text-gray-400 text-sm">This artifact's JSON could not be parsed.</p>;
  }

  return (
    <div className="text-sm">
      <JsonView data={data} shouldExpandNode={allExpanded} style={isDark ? darkStyles : defaultStyles} />
    </div>
  );
}
