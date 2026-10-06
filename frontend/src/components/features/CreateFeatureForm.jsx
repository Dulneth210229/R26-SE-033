import { useState } from "react";
import { useCreateFeature } from "../../hooks/useFeatures";
import ErrorBanner from "../common/ErrorBanner";

export default function CreateFeatureForm({ projectId, onCreated, onCancel }) {
  const [featureName, setFeatureName] = useState("");
  const [featureDescription, setFeatureDescription] = useState("");
  const createFeature = useCreateFeature(projectId);

  async function handleSubmit(event) {
    event.preventDefault();

    const feature = await createFeature.mutateAsync({
      feature_name: featureName.trim(),
      feature_description: featureDescription.trim(),
    });

    onCreated?.(feature);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <ErrorBanner error={createFeature.error} fallback="Failed to create feature." />

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Feature Name</label>
        <input
          required
          value={featureName}
          onChange={(event) => setFeatureName(event.target.value)}
          placeholder="Login"
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
      </div>

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Description</label>
        <textarea
          required
          value={featureDescription}
          onChange={(event) => setFeatureDescription(event.target.value)}
          placeholder="Allow users to log in using email and password."
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          rows={3}
        />
      </div>

      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="bg-gray-200 hover:bg-gray-300 dark:bg-white/10 dark:hover:bg-white/20 text-gray-800 dark:text-gray-200 font-semibold py-2 px-4 rounded"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={createFeature.isPending}
          className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
        >
          {createFeature.isPending ? "Creating..." : "Create Feature"}
        </button>
      </div>
    </form>
  );
}
