import { Route, Routes } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import ProtectedRoute from "./components/auth/ProtectedRoute";
import OAuthCallbackHandler from "./components/auth/OAuthCallbackHandler";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import ProjectListPage from "./pages/ProjectListPage";
import ProjectWorkspacePage from "./pages/ProjectWorkspacePage";
import LlmSettingsPage from "./pages/LlmSettingsPage";
import ProfilePage from "./pages/ProfilePage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/auth/callback" element={<OAuthCallbackHandler />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<ProjectListPage />} />
          <Route path="/projects/:projectId" element={<ProjectWorkspacePage />} />
          <Route path="/projects/:projectId/features/:featureId" element={<ProjectWorkspacePage />} />
          <Route path="/settings/llm" element={<LlmSettingsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
