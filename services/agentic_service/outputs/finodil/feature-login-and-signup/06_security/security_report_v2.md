# Security Report -- Finodil / Login and Signup

Generated: 2026-08-22T16:39:26.122820+00:00
Scan type: **Standard scan**
Gate decision: **FAIL**
Total findings: 3 (1 critical, 2 moderate, 0 warning)

## Critical

- **[CRITICAL]** `SEC-SECRET-MONGO-URI` (CWE-798) -- lib\mongodb.ts:6 -- MongoDB connection string with an embedded, hardcoded credential
  - Root cause: A hardcoded secret literal (mongodb connection string with an embedded, hardcoded credential) was found directly in source at lib\mongodb.ts:6.
  - Suggested fix: Move this value to `.env.local` (gitignored) and read it via `process.env.X` at runtime; rotate the exposed credential/key immediately, since it may already be compromised.

## Moderate

- **[HIGH]** `SEC-JS-005` (CWE-79) -- app\login-and-signup\page.tsx:166 -- dangerouslySetInnerHTML bypasses React's default escaping; unsanitized HTML here is stored/DOM XSS.
  - Root cause: A dangerouslySetInnerHTML attribute was found at app\login-and-signup\page.tsx:166, rendering raw HTML without React's default escaping.
  - Suggested fix: Remove dangerouslySetInnerHTML and render the content as plain text/JSX, or sanitize the HTML through a trusted library (e.g. DOMPurify) before rendering it.
- **[HIGH]** `SEC-LLM-REVIEW` (CWE-79) -- app\login-and-signup\page.tsx:166 -- Potential Insecure Direct Object References -- The use of dangerouslySetInnerHTML without proper sanitization can lead to Insecure Direct Object References (IDOR) if user input is improperly handled, allowing attackers to manipulate HTML content.
  - Root cause: The use of dangerouslySetInnerHTML without sanitization on line 166.
  - Suggested fix: Sanitize user input before setting it with dangerouslySetInnerHTML. Consider using a library like DOMPurify to ensure HTML content is safe.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

LLM review layer ran successfully: 1 additional finding(s).