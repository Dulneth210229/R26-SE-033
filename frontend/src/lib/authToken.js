// Single source of truth for where the JWT access token lives (localStorage) -- both the axios
// interceptor (client.js) and AuthContext.jsx read/write through these same functions so they
// can never drift out of sync on the storage key.
const STORAGE_KEY = "autoforge_access_token";

export function getToken() {
  return localStorage.getItem(STORAGE_KEY);
}

export function setToken(token) {
  localStorage.setItem(STORAGE_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(STORAGE_KEY);
}
