// The Requirement Agent's LLM calls are all JSON-contract calls (reliable parsing requires it),
// but streaming that raw JSON straight to the screen -- braces, quotes, "known_answers": -- reads
// as debug output, not a message or document "generating directly" the way ChatGPT/Claude's
// responses do. These helpers turn partial (possibly-incomplete, still-streaming) JSON text into
// something presentable, without needing the JSON to be complete or even valid yet.

// Extracts ONE string field's value out of partial JSON text as it streams in -- e.g. pulling
// just {"reaction": "Thanks for clarifying..."} 's reaction text out of a much larger, still-
// incomplete SRS-shaped JSON blob, so a chat bubble can show only that field growing, with no
// surrounding JSON syntax at all. Handles JSON escape sequences (\n, \", etc.) so the extracted
// text reads like real prose. Returns "" if the field hasn't started streaming yet, the partial
// value so far if it's still open, or the complete value once its closing quote arrives.
export function extractStreamingJsonStringField(rawText, fieldName) {
  if (!rawText) return "";

  const marker = `"${fieldName}"`;
  const markerIndex = rawText.indexOf(marker);
  if (markerIndex === -1) return "";

  let i = markerIndex + marker.length;
  const isSpace = (ch) => ch === " " || ch === "\n" || ch === "\t" || ch === "\r";

  while (i < rawText.length && isSpace(rawText[i])) i++;
  if (rawText[i] !== ":") return "";
  i++;
  while (i < rawText.length && isSpace(rawText[i])) i++;
  if (rawText[i] !== '"') return "";
  i++; // past the opening quote

  const ESCAPES = { n: "\n", t: "\t", r: "\r", '"': '"', "\\": "\\", "/": "/" };
  let result = "";

  while (i < rawText.length) {
    const ch = rawText[i];

    if (ch === "\\") {
      if (i + 1 >= rawText.length) break; // escape sequence not fully arrived yet -- stop cleanly
      const next = rawText[i + 1];
      result += ESCAPES[next] !== undefined ? ESCAPES[next] : next;
      i += 2;
      continue;
    }

    if (ch === '"') break; // closing quote -- field is complete

    result += ch;
    i++;
  }

  return result;
}

// Generic fallback for JSON that has no single "the message" field (e.g. the SRS document itself,
// where every field matters) -- strips structural noise (braces, brackets, quotes) and turns
// "snake_case_key": into "Snake Case Key:" so partial/streaming JSON reads more like a forming
// document than a raw data dump. Purely cosmetic string manipulation, not a real parser, so it
// degrades gracefully on incomplete/invalid JSON instead of needing valid input.
export function declutterJsonForDisplay(rawText) {
  if (!rawText) return "";

  return rawText
    // The LLM sometimes wraps its JSON output in a markdown code fence (```json ... ```) -- the
    // backend's own remove_markdown_code_fences (app/utils/json_utils.py) strips this from the
    // COMPLETE accumulated text after a stream ends, but the raw per-token SSE chunks forwarded
    // live to this display never went through it, so a leading ```json line rode straight through
    // as literal visible text. Mirrors the backend's exact regexes so both sides agree.
    .replace(/^\s*```json\s*/i, "")
    .replace(/^\s*```\s*/, "")
    .replace(/\s*```\s*$/, "")
    .replace(/"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:\s*/g, (_match, key) => `${humanizeKey(key)}: `)
    // Unescape JSON string-escape sequences BEFORE stripping quotes, or e.g. \" degrades to a
    // stray backslash instead of a real quote, and \n never becomes a real line break.
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "  ")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\")
    .replace(/[{}[\]]/g, "")
    .replace(/^[ \t]*,[ \t]*$/gm, "")
    .replace(/,[ \t]*$/gm, "")
    .replace(/"/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^\s+/, "");
}

function humanizeKey(key) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
