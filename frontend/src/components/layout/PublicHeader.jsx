import ThemeSwitcher from "./ThemeSwitcher";

// Header for pre-authentication pages (Login/Signup) -- visually matches AppShell.jsx's real
// header exactly (same background/border/padding/wordmark) but carries no Projects/LLM Settings
// links and no UserMenu, since neither makes sense before a user is signed in (clicking either
// would just bounce back here via ProtectedRoute).
export default function PublicHeader() {
  return (
    <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 flex-shrink-0">
      <div className="w-full px-6 py-3 flex items-center justify-between">
        <span className="text-lg font-bold text-gray-900 dark:text-gray-100">AutoForge</span>
        <ThemeSwitcher />
      </div>
    </header>
  );
}
