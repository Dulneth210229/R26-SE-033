import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";
import LoadingSpinner from "../common/LoadingSpinner";

// Wraps the existing <Route element={<AppShell/>}> subtree in App.jsx -- everything under it
// (Projects/LLM Settings/Profile/the workspace) requires a signed-in user. Preserves the
// original destination via location state so LoginPage can send the user back to where they
// were trying to go instead of always landing on "/".
export default function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-200 dark:bg-gray-950">
        <LoadingSpinner label="Loading..." />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <Outlet />;
}
