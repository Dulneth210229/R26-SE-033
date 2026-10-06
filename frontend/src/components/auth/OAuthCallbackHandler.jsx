import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import LoadingSpinner from "../common/LoadingSpinner";

// Route target for /auth/callback -- the backend's own Google/GitHub OAuth callback routes
// redirect the whole browser tab here with `#token=<jwt>` in the URL fragment (a fragment,
// not a query string, so the token never gets sent to or logged by any server along the
// redirect chain). Reads it once, adopts it into AuthContext, then redirects into the app.
export default function OAuthCallbackHandler() {
  const { adoptToken } = useAuth();
  const [status, setStatus] = useState("processing");

  useEffect(() => {
    const hash = window.location.hash;
    const match = hash.match(/token=([^&]+)/);

    if (!match) {
      setStatus("error");
      return;
    }

    adoptToken(decodeURIComponent(match[1]));
    // Clear the fragment so the token doesn't linger in browser history/the address bar.
    window.history.replaceState(null, "", window.location.pathname);
    setStatus("done");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once, on mount, reading the
    // URL fragment exactly once; adoptToken is a stable function from AuthContext.
  }, []);

  if (status === "error") {
    return <Navigate to="/login" replace />;
  }

  if (status === "done") {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="h-screen flex items-center justify-center bg-gray-200 dark:bg-gray-950">
      <LoadingSpinner label="Signing you in..." />
    </div>
  );
}
