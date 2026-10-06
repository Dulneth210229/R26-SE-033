# Security Report -- Finodil / Login and Signup

Generated: 2026-08-22T16:42:59.786505+00:00
Scan type: **AI model deep scan**
Gate decision: **FAIL**
Total findings: 8 (4 critical, 4 moderate, 0 warning)

## Critical

- **[CRITICAL]** `SEC-SECRET-MONGO-URI` (CWE-798) -- lib\mongodb.ts:6 -- MongoDB connection string with an embedded, hardcoded credential
  - Root cause: A hardcoded secret literal (mongodb connection string with an embedded, hardcoded credential) was found directly in source at lib\mongodb.ts:6.
  - Suggested fix: Move this value to `.env.local` (gitignored) and read it via `process.env.X` at runtime; rotate the exposed credential/key immediately, since it may already be compromised.
- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-943) -- app/api/auth/login/route.ts:27 -- NoSQL Injection via Query Parameters -- The code merges a client-supplied `filter` object directly into the MongoDB query, allowing for NoSQL injection attacks.
  - Root cause: const user = await LoginAndSignupData.findOne({ email, ...filter });
  - Suggested fix: Sanitize and validate the `filter` object to prevent injection attacks. Avoid directly merging client-supplied data into query parameters.
- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-916) -- app/api/auth/signup/route.ts:50 -- Weak Password Hashing Cost Factor -- The bcrypt cost factor is set to 1, which is far too weak and makes brute-forcing the hash cheap.
  - Root cause: const hashedPassword = await bcrypt.hash(password, 1);
  - Suggested fix: Use a stronger cost factor for hashing passwords, such as 10 or higher.
- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-798) -- lib/mongodb.ts:6 -- Hardcoded Secrets -- A hardcoded MongoDB connection string with a fake but realistic credential is present in the code.
  - Root cause: const FALLBACK_MONGODB_URI = "mongodb+srv://finodil_admin:Sup3rSecretPass!@cluster0.abcde.mongodb.net/finodil";
  - Suggested fix: Remove the hardcoded MongoDB connection string and use environment variables to store sensitive information.

## Moderate

- **[HIGH]** `SEC-JS-005` (CWE-79) -- app\login-and-signup\page.tsx:166 -- dangerouslySetInnerHTML bypasses React's default escaping; unsanitized HTML here is stored/DOM XSS.
  - Root cause: A dangerouslySetInnerHTML attribute was found at app\login-and-signup\page.tsx:166, rendering raw HTML without React's default escaping.
  - Suggested fix: Remove dangerouslySetInnerHTML and render the content as plain text/JSX, or sanitize the HTML through a trusted library (e.g. DOMPurify) before rendering it.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-532) -- app/api/auth/login/route.ts:14 -- Plaintext Password Logging -- The code logs the plaintext password, which can lead to sensitive information exposure if logs are accessed by unauthorized parties.
  - Root cause: console.log('Login attempt:', email, password);
  - Suggested fix: Remove or replace the line that logs the plaintext password.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-79) -- app/login-and-signup/page.tsx:104 -- Cross-Site Scripting (XSS) -- The error message is rendered using dangerouslySetInnerHTML, which can allow XSS attacks if the error message includes user input or unescaped data.
  - Root cause: dangerouslySetInnerHTML={{ __html: error }}
  - Suggested fix: Replace dangerouslySetInnerHTML with plain text rendering to prevent XSS. For example, use <div className="text-red-500 text-sm text-center">{error}</div>.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-798) -- models\LoginAndSignupData.ts:13 -- Password Storage in Plain Text -- The password field is stored in plain text, which poses a significant risk if the database is compromised.
  - Root cause: The password field is defined without any encryption or hashing.
  - Suggested fix: Hash the password using a strong cryptographic hash function before storing it in the database. Consider using bcrypt for this purpose.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

AI model deep scan ran over 3 batch(es) of real source code (3 succeeded, 0 failed): 6 finding(s).