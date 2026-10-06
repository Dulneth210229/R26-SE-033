import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import ErrorBanner from "../components/common/ErrorBanner";
import PasswordInput from "../components/common/PasswordInput";
import PublicHeader from "../components/layout/PublicHeader";

// Mirrors the backend's own bcrypt/pydantic rule (user_schema.py's _PASSWORD_PATTERN) so a
// weak password is caught here, with a clear inline message, instead of surfacing as a raw
// 422 validation-error array from the API.
const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [contactNumber, setContactNumber] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError({ message: "Password and confirm password do not match." });
      return;
    }
    if (!PASSWORD_PATTERN.test(password)) {
      setError({ message: "Password must be at least 8 characters and include a letter and a digit." });
      return;
    }

    setIsSubmitting(true);
    try {
      await register({
        email: email.trim(),
        contact_number: contactNumber.trim(),
        password,
        confirm_password: confirmPassword,
      });
      navigate("/", { replace: true });
    } catch (submitError) {
      setError(submitError);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="h-screen flex flex-col bg-gray-200 dark:bg-gray-950">
      <PublicHeader />
      <div className="flex-1 flex items-center justify-center px-4 py-8 overflow-y-auto">
      <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-lg shadow p-6">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-1">Create your account</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">Get started with AutoForge</p>

        <ErrorBanner error={error} fallback="Sign-up failed." />

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
            <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Contact Number</label>
            <input
              required
              type="tel"
              value={contactNumber}
              onChange={(event) => setContactNumber(event.target.value)}
              placeholder="+1 555-123-4567"
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
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">At least 8 characters, with a letter and a digit.</p>
          </div>

          <div>
            <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Confirm Password</label>
            <PasswordInput
              required
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
          >
            {isSubmitting ? "Creating account..." : "Create Account"}
          </button>
        </form>

        <p className="text-sm text-gray-500 dark:text-gray-400 mt-6 text-center">
          Already have an account?{" "}
          <Link to="/login" className="text-accent-600 dark:text-accent-400 font-semibold hover:underline">
            Sign in
          </Link>
        </p>
      </div>
      </div>
    </div>
  );
}
