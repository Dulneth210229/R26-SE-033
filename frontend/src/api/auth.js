import { API_BASE_URL, apiClient } from "./client";

export async function register({ email, contact_number, password, confirm_password }) {
  const { data } = await apiClient.post("/auth/register", {
    email,
    contact_number,
    password,
    confirm_password,
  });
  return data;
}

export async function login({ email, password }) {
  const { data } = await apiClient.post("/auth/login", { email, password });
  return data;
}

export async function getMe() {
  const { data } = await apiClient.get("/auth/me");
  return data;
}

export async function updateProfile({ name, contact_number, profile_picture_url }) {
  const { data } = await apiClient.put("/profile", { name, contact_number, profile_picture_url });
  return data;
}

export async function updatePassword({ current_password, new_password }) {
  await apiClient.put("/profile/password", { current_password, new_password });
}

// Plain navigations, not axios calls -- the backend redirects the whole browser tab to the
// provider's consent screen, then back to /auth/callback with a real token.
export function googleLoginUrl() {
  return `${API_BASE_URL}/auth/google/login`;
}

export function githubLoginUrl() {
  return `${API_BASE_URL}/auth/github/login`;
}
