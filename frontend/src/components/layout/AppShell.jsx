import { Link, Outlet, useLocation } from "react-router-dom";
import clsx from "clsx";
import ThemeSwitcher from "./ThemeSwitcher";
import UserMenu from "./UserMenu";

const NAV_ITEMS = [
  { to: "/", label: "Projects" },
  { to: "/settings/llm", label: "LLM Settings" },
];

export default function AppShell() {
  const location = useLocation();

  return (
    <div className="h-screen flex flex-col bg-gray-200 dark:bg-gray-950">
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 flex-shrink-0">
        <div className="w-full px-6 py-3 flex items-center justify-between">
          <Link to="/" className="text-lg font-bold text-gray-900 dark:text-gray-100">
            AutoForge
          </Link>
          <div className="flex items-center gap-4">
            <nav className="flex gap-4">
              {NAV_ITEMS.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className={clsx(
                    "text-sm font-medium px-3 py-1.5 rounded",
                    location.pathname === item.to
                      ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
                      : "text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <ThemeSwitcher />
            <UserMenu />
          </div>
        </div>
      </header>
      {/* No overflow/scroll here on purpose -- exactly one scroll context per page, chosen by
          the page itself. Two nested "overflow-y-auto" ancestors (this one, plus each page's own
          internal scroll areas) fight each other: whichever is a few px taller than its share of
          the viewport silently engages ITS OWN scroll too, on top of the inner ones -- confirmed
          as the real cause of a reported "scrolling issue" on the feature dashboard. Each page is
          responsible for its own `h-full overflow-y-auto` (simple pages) or its own precise
          flex-fill layout (FeatureDetailPage). */}
      <main className="flex-1 min-h-0 w-full px-6 py-6 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
