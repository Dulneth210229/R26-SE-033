// Generic "render any JSON value like part of a document" helper -- used for the parts of
// SRS/Architecture Plan JSON too deeply nested/variable to hand-write a bespoke layout for
// (e.g. Architecture Plan's 8 design_views sub-views). Strings become prose, string arrays
// become bullet lists, arrays of flat objects become tables, arrays of nested objects and plain
// objects recurse -- always readable, never a raw JSON dump.
export function humanizeKey(key) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function isTableCellValue(v) {
  if (v === null || typeof v !== "object") return true;
  // An array of primitives (e.g. related_acceptance_criteria: ["AC-001"]) still fits in one
  // table cell (joined with ", ") -- only an array containing an object forces the row out of
  // table form.
  if (Array.isArray(v)) return v.every((item) => item === null || typeof item !== "object");
  // A plain nested object still fits a table cell if every one of ITS OWN fields is itself a
  // scalar/flat array -- e.g. domain_citation: {source_document, chunk_id}. Rendered as a compact
  // "key: value" summary (see the <td> render below) instead of disqualifying the whole row --
  // previously a single Domain-Agent-enriched item (the only kind of row that carries this shape)
  // broke table rendering for the ENTIRE array, falling every row back to stacked label cards.
  return Object.values(v).every((vv) => vv === null || typeof vv !== "object");
}

function isFlatObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) && Object.values(value).every(isTableCellValue);
}

export default function DocumentValue({ value }) {
  if (value === null || value === undefined || value === "") return null;

  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{String(value)}</p>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return <p className="text-sm text-gray-400 dark:text-gray-500 italic">None</p>;

    if (value.every((v) => typeof v === "string" || typeof v === "number")) {
      return (
        <ul className="list-disc list-inside text-sm text-gray-700 dark:text-gray-300 space-y-0.5">
          {value.map((v, i) => (
            <li key={i}>{v}</li>
          ))}
        </ul>
      );
    }

    if (value.every(isFlatObject)) {
      const columns = [...new Set(value.flatMap((row) => Object.keys(row)))];
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700">
                {columns.map((col) => (
                  <th key={col} className="text-left font-semibold text-gray-500 dark:text-gray-400 py-1 pr-3 whitespace-nowrap">
                    {humanizeKey(col)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {value.map((row, i) => (
                <tr key={i} className="border-b border-gray-100 dark:border-gray-800 last:border-0">
                  {columns.map((col) => (
                    <td key={col} className="py-1.5 pr-3 text-gray-700 dark:text-gray-300 align-top">
                      {row[col] === undefined || row[col] === null || row[col] === "" ? (
                        <span className="text-gray-300 dark:text-gray-600">--</span>
                      ) : Array.isArray(row[col]) ? (
                        row[col].join(", ")
                      ) : typeof row[col] === "object" ? (
                        <span className="text-xs italic text-gray-400 dark:text-gray-500">
                          {Object.entries(row[col])
                            .filter(([, vv]) => vv !== null && vv !== undefined && vv !== "")
                            .map(([kk, vv]) => `${humanizeKey(kk)}: ${vv}`)
                            .join(", ")}
                        </span>
                      ) : (
                        String(row[col])
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    return (
      <div className="flex flex-col gap-2">
        {value.map((v, i) => (
          <div key={i} className="border-l-2 border-gray-200 dark:border-gray-700 pl-2">
            <DocumentValue value={v} />
          </div>
        ))}
      </div>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value).filter(([, v]) => v !== null && v !== undefined && v !== "");
    if (entries.length === 0) return null;

    return (
      <div className="flex flex-col gap-2">
        {entries.map(([k, v]) => (
          <div key={k}>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">{humanizeKey(k)}</p>
            <DocumentValue value={v} />
          </div>
        ))}
      </div>
    );
  }

  return null;
}
