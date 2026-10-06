import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";

function LogoutIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-4 h-4 flex-shrink-0">
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
    </svg>
  );
}

function Avatar({ user }) {
  if (user?.profile_picture_url) {
    return <img src={user.profile_picture_url} alt={user.name || user.email} className="w-9 h-9 rounded-full object-cover flex-shrink-0" />;
  }
  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();
  return (
    <div className="w-9 h-9 rounded-full bg-accent-600 text-white flex items-center justify-center text-sm font-bold flex-shrink-0">
      {initial}
    </div>
  );
}

// Nav-bar user chip -- avatar + name + email, matching the reference image -- click opens a
// small dropdown for Profile/Log out (the same two actions the earlier sidebar's own user menu
// exposed, still needed even though the dashboard-sidebar layout itself was reverted).
export default function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function handleLogout() {
    setOpen(false);
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-white/10"
      >
        <Avatar user={user} />
        <div className="min-w-0 text-left hidden sm:block">
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate max-w-[160px]">
            {user?.name || "Account"}
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-500 truncate max-w-[160px]">{user?.email}</p>
        </div>
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-2 w-48 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-1 z-20">
          <Link
            to="/profile"
            onClick={() => setOpen(false)}
            className="block px-3 py-2 rounded text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            Profile
          </Link>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-3 py-2 rounded text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
          >
            <LogoutIcon />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
