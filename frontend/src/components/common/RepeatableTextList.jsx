import { useState } from "react";

// Generic "add item / remove item" list editor, reused for every string[] field in the
// Requirement Agent BA input form (functional_requirements, user_roles, constraints, ...).
export default function RepeatableTextList({ label, value, onChange, placeholder }) {
  const [draft, setDraft] = useState("");

  function addItem() {
    const trimmed = draft.trim();

    if (!trimmed) {
      return;
    }

    onChange([...value, trimmed]);
    setDraft("");
  }

  function removeItem(index) {
    onChange(value.filter((_, i) => i !== index));
  }

  function handleKeyDown(event) {
    if (event.key === "Enter") {
      event.preventDefault();
      addItem();
    }
  }

  return (
    <div>
      <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">{label}</label>

      {value.length > 0 && (
        <ul className="mb-2 flex flex-col gap-1">
          {value.map((item, index) => (
            <li
              key={index}
              className="flex items-center justify-between bg-gray-100 dark:bg-white/10 text-gray-900 dark:text-gray-200 text-sm px-3 py-1.5 rounded"
            >
              <span>{item}</span>
              <button
                type="button"
                onClick={() => removeItem(index)}
                className="text-gray-400 hover:text-red-600 dark:text-gray-500 dark:hover:text-red-400 ml-2"
                aria-label={`Remove ${item}`}
              >
                &times;
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="flex-1 p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
        <button
          type="button"
          onClick={addItem}
          className="bg-gray-200 hover:bg-gray-300 dark:bg-white/10 dark:hover:bg-white/20 text-gray-700 dark:text-gray-200 text-sm font-semibold px-3 rounded"
        >
          Add
        </button>
      </div>
    </div>
  );
}
