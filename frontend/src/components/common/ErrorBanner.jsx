export default function ErrorBanner({ error, fallback = "Something went wrong." }) {
  if (!error) {
    return null;
  }

  const message = error?.response?.data?.detail || error?.message || fallback;

  return <p className="bg-red-100 dark:bg-red-500/15 text-red-700 dark:text-red-300 text-sm p-3 rounded mb-4">{message}</p>;
}
