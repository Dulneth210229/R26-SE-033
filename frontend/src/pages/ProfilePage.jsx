import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import PageHeader from "../components/layout/PageHeader";
import ErrorBanner from "../components/common/ErrorBanner";
import { useAuth } from "../contexts/AuthContext";
import * as authApi from "../api/auth";

function Avatar({ user, size = 64 }) {
  if (user?.profile_picture_url) {
    return (
      <img
        src={user.profile_picture_url}
        alt={user.name || user.email}
        style={{ width: size, height: size }}
        className="rounded-full object-cover"
      />
    );
  }
  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();
  return (
    <div
      style={{ width: size, height: size }}
      className="rounded-full bg-accent-600 text-white flex items-center justify-center font-bold"
    >
      {initial}
    </div>
  );
}

export default function ProfilePage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const [name, setName] = useState(user?.name || "");
  const [contactNumber, setContactNumber] = useState(user?.contact_number || "");
  const [profilePictureUrl, setProfilePictureUrl] = useState(user?.profile_picture_url || "");

  useEffect(() => {
    if (user) {
      setName(user.name || "");
      setContactNumber(user.contact_number || "");
      setProfilePictureUrl(user.profile_picture_url || "");
    }
  }, [user]);

  const updateProfile = useMutation({
    mutationFn: authApi.updateProfile,
    onSuccess: (updated) => queryClient.setQueryData(["me"], updated),
  });

  async function handleProfileSubmit(event) {
    event.preventDefault();
    await updateProfile.mutateAsync({
      name: name.trim(),
      contact_number: contactNumber.trim(),
      profile_picture_url: profilePictureUrl.trim(),
    });
  }

  const isOAuthOnly = user?.auth_provider !== "password";

  return (
    <div className="h-full overflow-y-auto pr-1.5">
      <PageHeader title="Profile" subtitle="View and update your account details." />

      <div className="max-w-4xl flex flex-col gap-6">
        <div className="flex items-center gap-4">
          <Avatar user={user} />
          <div>
            <p className="font-semibold text-gray-900 dark:text-gray-100">{user?.name || "Unnamed User"}</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">{user?.email}</p>
          </div>
        </div>

        {/* Two columns once there's room (Account Details left, Change Password right);
            stacks back to one column on narrow/laptop widths -- same content, same forms,
            only the layout changes. Grid's default `items: stretch` (no `items-start` override)
            makes both cards match the taller one's height; each form's own `h-full` + the
            button row's `mt-auto` is what lets the extra height land as bottom padding under
            the button rather than the button floating in the middle of a stretched card. */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <form onSubmit={handleProfileSubmit} className="h-full bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800 p-5 flex flex-col gap-4">
          <h2 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Account Details</h2>

          <ErrorBanner error={updateProfile.error} fallback="Failed to update profile." />

          <div>
            <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Name</label>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Contact Number</label>
            <input
              value={contactNumber}
              onChange={(event) => setContactNumber(event.target.value)}
              className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Profile Picture URL</label>
            <input
              value={profilePictureUrl}
              onChange={(event) => setProfilePictureUrl(event.target.value)}
              placeholder="https://example.com/avatar.png"
              className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Email</label>
            <input
              disabled
              value={user?.email || ""}
              className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-white/5 dark:text-gray-400 rounded-md"
            />
          </div>

          <div className="flex justify-end mt-auto">
            <button
              type="submit"
              disabled={updateProfile.isPending}
              className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
            >
              {updateProfile.isPending ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </form>

        <PasswordSection isOAuthOnly={isOAuthOnly} />
        </div>
      </div>
    </div>
  );
}

function PasswordSection({ isOAuthOnly }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [localError, setLocalError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  const updatePassword = useMutation({
    mutationFn: authApi.updatePassword,
  });

  async function handleSubmit(event) {
    event.preventDefault();
    setLocalError(null);
    setSuccessMessage(null);

    if (newPassword !== confirmNewPassword) {
      setLocalError({ message: "New password and confirm password do not match." });
      return;
    }

    await updatePassword.mutateAsync({ current_password: currentPassword, new_password: newPassword });
    setCurrentPassword("");
    setNewPassword("");
    setConfirmNewPassword("");
    setSuccessMessage("Password updated.");
  }

  if (isOAuthOnly) {
    return (
      <div className="h-full bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800 p-5">
        <h2 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-2">Password</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          This account signs in via Google/GitHub and has no password to change.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="h-full bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800 p-5 flex flex-col gap-4">
      <h2 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide">Change Password</h2>

      <ErrorBanner error={localError || updatePassword.error} fallback="Failed to update password." />
      {successMessage && (
        <p className="bg-green-100 dark:bg-green-500/15 text-green-700 dark:text-green-300 text-sm p-3 rounded">
          {successMessage}
        </p>
      )}

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Current Password</label>
        <input
          required
          type="password"
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
      </div>

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">New Password</label>
        <input
          required
          type="password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
      </div>

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Confirm New Password</label>
        <input
          required
          type="password"
          value={confirmNewPassword}
          onChange={(event) => setConfirmNewPassword(event.target.value)}
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
      </div>

      <div className="flex justify-end mt-auto">
        <button
          type="submit"
          disabled={updatePassword.isPending}
          className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
        >
          {updatePassword.isPending ? "Updating..." : "Update Password"}
        </button>
      </div>
    </form>
  );
}
