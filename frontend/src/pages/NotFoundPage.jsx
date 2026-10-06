import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="text-center py-16">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Page not found</h1>
      <Link to="/" className="text-accent-600 dark:text-accent-400 hover:underline mt-4 inline-block">
        Back to Projects
      </Link>
    </div>
  );
}
