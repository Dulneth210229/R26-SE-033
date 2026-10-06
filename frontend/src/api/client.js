import axios from "axios";
import { clearToken, getToken } from "../lib/authToken";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

apiClient.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// A 401 means the token is missing/expired/invalid -- clear it and send the user back to
// /login rather than leaving the app stuck showing a broken, half-authenticated screen. Skips
// this for the login/register calls themselves (a wrong password is a normal 401, not a
// "your session died" event) -- those already show their own inline error instead.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const isAuthEndpoint = error.config?.url?.startsWith("/auth/login") || error.config?.url?.startsWith("/auth/register");
    if (error.response?.status === 401 && !isAuthEndpoint) {
      clearToken();
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

// These URLs are used directly in <img src>/<a href> (artifact previews, downloads, code zips)
// -- a plain browser-initiated request can't attach a custom Authorization header, so the token
// travels as a query param instead (get_current_user accepts either -- see app/api/deps.py).
function withToken(url) {
  const token = getToken();
  if (!token) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(token)}`;
}

export function artifactContentUrl(artifactId) {
  return withToken(`${API_BASE_URL}/artifacts/${artifactId}/content`);
}

export function artifactDownloadUrl(artifactId) {
  return withToken(`${API_BASE_URL}/artifacts/${artifactId}/download`);
}

export function artifactDownloadPdfUrl(artifactId) {
  return withToken(`${API_BASE_URL}/artifacts/${artifactId}/download-pdf`);
}

export function featureCodeDownloadUrl(featureId) {
  return withToken(`${API_BASE_URL}/features/${featureId}/code/download`);
}

export function featureCodeWithQaReportDownloadUrl(featureId) {
  return withToken(`${API_BASE_URL}/features/${featureId}/code-with-qa-report/download`);
}

export function featureUiuxImagesDownloadUrl(featureId, version) {
  return withToken(`${API_BASE_URL}/features/${featureId}/uiux-images/${version}/download`);
}

export function projectCodeDownloadUrl(projectId) {
  return withToken(`${API_BASE_URL}/projects/${projectId}/code/download`);
}
