import { useState } from "react";
import { useRunRequirement } from "../../hooks/useAgentMutations";
import RepeatableTextList from "../common/RepeatableTextList";
import ErrorBanner from "../common/ErrorBanner";

const ARCHITECTURAL_STYLES = ["modular", "monolithic", "mvc", "microservices", "layered", "clean_architecture"];

function emptyBaInput(feature) {
  return {
    project_type: "",
    feature_name: feature?.feature_name || "",
    target_stack: "Next.js",
    architectural_style: "modular",
    user_roles: [],
    business_goal: "",
    functional_requirements: [],
    non_functional_requirements: [],
    acceptance_criteria: [],
    ui_expectations: [],
    api_expectations: [],
    data_requirements: [],
    constraints: [],
    assumptions: [],
  };
}

export default function RequirementRunForm({ featureId, feature }) {
  const [baInput, setBaInput] = useState(() => emptyBaInput(feature));
  const [humanComment, setHumanComment] = useState("");
  const runRequirement = useRunRequirement(featureId);

  function set(field, val) {
    setBaInput((current) => ({ ...current, [field]: val }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    await runRequirement.mutateAsync({ ba_input: baInput, human_comment: humanComment.trim() || null });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 bg-white dark:bg-gray-900 p-6 rounded-lg shadow-sm border border-gray-200 dark:border-gray-800">
      <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">Run Requirement Agent</h3>
      <p className="text-sm text-gray-500 dark:text-gray-400 -mt-2">
        Fill in what you know -- the agent fills reasonable gaps and records its assumptions.
      </p>

      <ErrorBanner error={runRequirement.error} fallback="Requirement Agent run failed." />

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Project Type</label>
          <input
            value={baInput.project_type}
            onChange={(e) => set("project_type", e.target.value)}
            placeholder="E-commerce"
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
        </div>
        <div>
          <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Feature Name</label>
          <input
            value={baInput.feature_name}
            onChange={(e) => set("feature_name", e.target.value)}
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
        </div>
        <div>
          <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Target Stack</label>
          <input
            value={baInput.target_stack}
            onChange={(e) => set("target_stack", e.target.value)}
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
        </div>
        <div>
          <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Architectural Style</label>
          <select
            value={baInput.architectural_style}
            onChange={(e) => set("architectural_style", e.target.value)}
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          >
            {ARCHITECTURAL_STYLES.map((style) => (
              <option key={style} value={style}>
                {style}
              </option>
            ))}
          </select>
        </div>
      </div>

      <RepeatableTextList
        label="User Roles"
        value={baInput.user_roles}
        onChange={(v) => set("user_roles", v)}
        placeholder="Admin"
      />

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Business Goal</label>
        <textarea
          value={baInput.business_goal}
          onChange={(e) => set("business_goal", e.target.value)}
          rows={2}
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
      </div>

      <RepeatableTextList
        label="Functional Requirements"
        value={baInput.functional_requirements}
        onChange={(v) => set("functional_requirements", v)}
        placeholder="Admin can add a new item to the catalog"
      />
      <RepeatableTextList
        label="Non-Functional Requirements"
        value={baInput.non_functional_requirements}
        onChange={(v) => set("non_functional_requirements", v)}
        placeholder="Operations should complete within 2 seconds"
      />
      <RepeatableTextList
        label="Acceptance Criteria"
        value={baInput.acceptance_criteria}
        onChange={(v) => set("acceptance_criteria", v)}
        placeholder="Given valid input, the item is created"
      />
      <RepeatableTextList
        label="UI Expectations"
        value={baInput.ui_expectations}
        onChange={(v) => set("ui_expectations", v)}
        placeholder="Item list table with add/edit/delete actions"
      />
      <RepeatableTextList
        label="API Expectations"
        value={baInput.api_expectations}
        onChange={(v) => set("api_expectations", v)}
        placeholder="POST /api/items"
      />
      <RepeatableTextList
        label="Data Requirements"
        value={baInput.data_requirements}
        onChange={(v) => set("data_requirements", v)}
        placeholder="Item name"
      />
      <RepeatableTextList
        label="Constraints"
        value={baInput.constraints}
        onChange={(v) => set("constraints", v)}
        placeholder="Use Next.js with TypeScript"
      />
      <RepeatableTextList
        label="Assumptions"
        value={baInput.assumptions}
        onChange={(v) => set("assumptions", v)}
        placeholder="Admin authentication already exists"
      />

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Human Comment (optional)</label>
        <textarea
          value={humanComment}
          onChange={(e) => setHumanComment(e.target.value)}
          rows={2}
          placeholder="Add forgot password requirement."
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
      </div>

      <button
        type="submit"
        disabled={runRequirement.isPending}
        className="self-start bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
      >
        {runRequirement.isPending ? "Generating SRS..." : "Run Requirement Agent"}
      </button>
    </form>
  );
}
