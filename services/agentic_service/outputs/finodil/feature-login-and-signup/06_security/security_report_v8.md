# Security Report -- Finodil / Login and Signup

Generated: 2026-08-25T04:44:33.738850+00:00
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
- **[HIGH]** `SEC-LLM-REVIEW` (CWE-89) -- app\login-and-signup\page.tsx:166 -- Potential SQL Injection Risk -- The use of dangerouslySetInnerHTML without proper sanitization could lead to a SQL injection vulnerability if user input is involved.
  - Root cause: The use of dangerouslySetInnerHTML without sanitization could allow malicious HTML to be executed, which might include SQL injection payloads.
  - Suggested fix: Sanitize all user inputs and consider using safer alternatives like React's built-in methods for rendering content.

## Dependency scan

npm audit exit code: 1
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {}

## LLM review layer

LLM review layer ran successfully: 1 additional finding(s).