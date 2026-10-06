import { Component } from "react";

// React only supports error boundaries via class components (no hook equivalent). Wrapped once
// at the app root (see main.jsx) so an uncaught render error in any single component -- e.g. a
// query settling into an error state that a child didn't null-guard against -- shows a
// recoverable message instead of silently unmounting the entire app to a blank page.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Unhandled render error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="h-screen flex items-center justify-center bg-gray-100 dark:bg-gray-950 px-6">
          <div className="max-w-md text-center">
            <h1 className="text-lg font-bold text-gray-900 dark:text-gray-100">Something went wrong</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
              {this.state.error.message || "An unexpected error occurred."}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="mt-4 bg-accent-600 hover:bg-accent-700 text-white font-semibold py-2 px-4 rounded"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
