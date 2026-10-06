# Security Report -- Finodil / Login and Signup

Generated: 2026-08-23T05:33:45.115314+00:00
Scan type: **AI model deep scan**
Gate decision: **FAIL**
Total findings: 7 (2 critical, 5 moderate, 0 warning)

## Critical

- **[CRITICAL]** `SEC-SECRET-MONGO-URI` (CWE-798) -- lib\mongodb.ts:6 -- MongoDB connection string with an embedded, hardcoded credential
  - Root cause: A hardcoded secret literal (mongodb connection string with an embedded, hardcoded credential) was found directly in source at lib\mongodb.ts:6.
  - Suggested fix: Move this value to `.env.local` (gitignored) and read it via `process.env.X` at runtime; rotate the exposed credential/key immediately, since it may already be compromised.
- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-943) -- app/api/auth/login/route.ts:35 -- NoSQL Injection via Query Parameters -- The login endpoint merges a client-supplied `filter` object directly into the MongoDB query, allowing for NoSQL injection attacks.
  - Root cause: const user = await LoginAndSignupData.findOne({ email, ...filter });
  - Suggested fix: Sanitize or validate the `filter` object to prevent injection attacks.

## Moderate

- **[HIGH]** `SEC-JS-005` (CWE-79) -- app\login-and-signup\page.tsx:166 -- dangerouslySetInnerHTML bypasses React's default escaping; unsanitized HTML here is stored/DOM XSS.
  - Root cause: A dangerouslySetInnerHTML attribute was found at app\login-and-signup\page.tsx:166, rendering raw HTML without React's default escaping.
  - Suggested fix: Remove dangerouslySetInnerHTML and render the content as plain text/JSX, or sanitize the HTML through a trusted library (e.g. DOMPurify) before rendering it.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-532) -- app/api/auth/login/route.ts:17 -- Plaintext Password Logging -- The login endpoint logs the plaintext password to the console, which can lead to sensitive information exposure.
  - Root cause: console.log('Login attempt:', email, password);
  - Suggested fix: Remove or replace the line that logs the plaintext password.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-916) -- app/api/auth/signup/route.ts:54 -- Weak Bcrypt Cost Factor -- The signup endpoint uses a bcrypt cost factor of 1, which is too weak and makes brute-forcing the hash cheap.
  - Root cause: const hashedPassword = await bcrypt.hash(password, 1);
  - Suggested fix: Increase the bcrypt cost factor to a value of at least 10.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-79) -- app\login-and-signup\page.tsx:145 -- Cross-Site Scripting (XSS) Vulnerability -- The error message is rendered using dangerouslySetInnerHTML without proper sanitization, which can allow an attacker to inject malicious scripts.
  - Root cause: The use of dangerouslySetInnerHTML with the error message variable that can include unsanitized user input.
  - Suggested fix: Sanitize the error message before rendering it using dangerouslySetInnerHTML. Consider using a library like DOMPurify to sanitize HTML content.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-798) -- lib\mongodb.ts:5 -- Hardcoded MongoDB Connection String -- The code contains a hardcoded MongoDB connection string with an embedded, fake-but-realistic credential. This can lead to unauthorized access if the code is exposed or misused.
  - Root cause: The hardcoded MongoDB URI with credentials: `const FALLBACK_MONGODB_URI = "mongodb+srv://finodil_admin:Sup3rSecretPass!@cluster0.abcde.mongodb.net/finodil";`
  - Suggested fix: Remove the hardcoded connection string and use environment variables to store sensitive information securely.

## Dependency scan

npm audit exit code: 1
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {}

## LLM review layer

AI model deep scan ran over 4 batch(es) of real source code (4 succeeded, 0 failed): 5 finding(s).