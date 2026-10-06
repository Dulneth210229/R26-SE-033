import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import ErrorBanner from "../components/common/ErrorBanner";
import PasswordInput from "../components/common/PasswordInput";
import PublicHeader from "../components/layout/PublicHeader";

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="w-4 h-4" aria-hidden="true">
      <path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47a5.6 5.6 0 0 1-2.4 3.65v3h3.86c2.26-2.09 3.56-5.17 3.56-8.89Z" />
      <path fill="#34A853" d="M12 24c3.24 0 5.95-1.07 7.93-2.9l-3.86-3c-1.07.72-2.45 1.15-4.07 1.15-3.13 0-5.78-2.11-6.73-4.96H1.28v3.11A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.27 14.29a7.2 7.2 0 0 1 0-4.58V6.6H1.28a12 12 0 0 0 0 10.8l3.99-3.11Z" />
      <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0A12 12 0 0 0 1.28 6.6l3.99 3.11C6.22 6.86 8.87 4.75 12 4.75Z" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24" className="w-4 h-4" fill="currentColor" aria-hidden="true">
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.1.78-.25.78-.55v-2.16c-3.2.7-3.87-1.36-3.87-1.36-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.17.08 1.78 1.2 1.78 1.2 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.23-1.28-5.23-5.68 0-1.25.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.05 11.05 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.64 1.59.24 2.76.12 3.05.74.8 1.19 1.83 1.19 3.08 0 4.41-2.69 5.38-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .3.21.66.79.55A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
    </svg>
  );
}

export default function LoginPage() {
  const { login, loginWithGoogle, loginWithGitHub } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await login(email.trim(), password);
      navigate(location.state?.from?.pathname || "/", { replace: true });
    } catch (submitError) {
      setError(submitError);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="h-screen flex flex-col bg-gray-200 dark:bg-gray-950">
      <PublicHeader />
      <div className="flex-1 flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-lg shadow p-6">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-1">Welcome back</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">Sign in to your account</p>

        <ErrorBanner error={error} fallback="Sign-in failed." />

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Email</label>
            <input
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Password</label>
            <PasswordInput
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
          >
            {isSubmitting ? "Signing in..." : "Sign In"}
          </button>
        </form>

        <div className="flex items-center gap-3 my-5">
          <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
          <span className="text-xs text-gray-400 dark:text-gray-500">or continue with</span>
          <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
        </div>

        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={loginWithGoogle}
            className="flex items-center justify-center gap-2 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-white/5 text-gray-700 dark:text-gray-200 font-semibold py-2 px-4 rounded"
          >
            <GoogleIcon />
            Continue with Google
          </button>
          <button
            type="button"
            onClick={loginWithGitHub}
            className="flex items-center justify-center gap-2 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-white/5 text-gray-700 dark:text-gray-200 font-semibold py-2 px-4 rounded"
          >
            <GitHubIcon />
            Continue with GitHub
          </button>
        </div>

        <p className="text-sm text-gray-500 dark:text-gray-400 mt-6 text-center">
          Don&apos;t have an account?{" "}
          <Link to="/register" className="text-accent-600 dark:text-accent-400 font-semibold hover:underline">
            Sign up
          </Link>
        </p>
      </div>
      </div>
    </div>
  );
}
