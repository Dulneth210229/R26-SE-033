import { createContext, useContext, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as authApi from "../api/auth";
import { clearToken, getToken, setToken } from "../lib/authToken";

const AuthContext = createContext(null);

// The first genuinely app-global context in this codebase (every existing context --
// WorkspaceSelectionContext and the per-agent "Flow" contexts -- is mounted inside
// ProjectWorkspacePage, scoped to one feature). Mirrors WorkspaceSelectionContext's own shape:
// a plain createContext(null), a provider that computes/memoizes one value object, and a
// paired useAuth() hook that throws outside the provider.
//
// The signed-in user is held via React Query (queryKey ["me"]) rather than a second useState --
// GET /auth/me is the single source of truth for "who am I," and login/register/logout all just
// write straight into that same cache entry (setQueryData) instead of juggling two copies of the
// same data that could drift out of sync.
export function AuthProvider({ children }) {
  const queryClient = useQueryClient();
  const [hasToken, setHasToken] = useState(() => Boolean(getToken()));

  const { data: user, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: authApi.getMe,
    enabled: hasToken,
    retry: false,
    staleTime: Infinity,
  });

  async function login(email, password) {
    const result = await authApi.login({ email, password });
    setToken(result.access_token);
    setHasToken(true);
    queryClient.setQueryData(["me"], result.user);
  }

  async function register({ email, contact_number, password, confirm_password }) {
    const result = await authApi.register({ email, contact_number, password, confirm_password });
    setToken(result.access_token);
    setHasToken(true);
    queryClient.setQueryData(["me"], result.user);
  }

  // Used by OAuthCallbackHandler -- the backend already issued the token and redirected here
  // with it in the URL fragment; this just adopts it, same as login()/register() do after their
  // own direct API call.
  function adoptToken(accessToken) {
    setToken(accessToken);
    setHasToken(true);
    queryClient.invalidateQueries({ queryKey: ["me"] });
  }

  function logout() {
    clearToken();
    setHasToken(false);
    queryClient.setQueryData(["me"], undefined);
    queryClient.clear();
  }

  function loginWithGoogle() {
    window.location.href = authApi.googleLoginUrl();
  }

  function loginWithGitHub() {
    window.location.href = authApi.githubLoginUrl();
  }

  const value = useMemo(
    () => ({
      user: user ?? null,
      isAuthenticated: Boolean(user),
      isLoading: hasToken && isLoading,
      login,
      register,
      logout,
      loginWithGoogle,
      loginWithGitHub,
      adoptToken,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- login/register/logout/etc. close
    // over stable module-level imports (authApi, token helpers) and queryClient (itself stable),
    // so they never need to be in this list -- only their identity changing would matter here,
    // and it never does.
    [user, hasToken, isLoading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
