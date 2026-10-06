# Security Report -- Finodil / Login and Signup

Generated: 2026-08-22T17:08:15.053613+00:00
Scan type: **AI model deep scan**
Gate decision: **FAIL**
Total findings: 8 (4 critical, 4 moderate, 0 warning)

## Critical

- **[CRITICAL]** `SEC-SECRET-MONGO-URI` (CWE-798) -- lib\mongodb.ts:6 -- MongoDB connection string with an embedded, hardcoded credential
  - Root cause: A hardcoded secret literal (mongodb connection string with an embedded, hardcoded credential) was found directly in source at lib\mongodb.ts:6.
  - Suggested fix: Move this value to `.env.local` (gitignored) and read it via `process.env.X` at runtime; rotate the exposed credential/key immediately, since it may already be compromised.
- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-943) -- app/api/auth/login/route.ts:31 -- NoSQL Injection via Query Parameters -- The login endpoint merges a client-supplied `filter` object directly into the MongoDB query, allowing for NoSQL injection attacks.
  - Root cause: const user = await LoginAndSignupData.findOne({ email, ...filter });
  - Suggested fix: Sanitize and validate the `filter` object to prevent injection attacks. Avoid using client-supplied parameters directly in database queries.
- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-916) -- app/api/auth/signup/route.ts:57 -- Weak Password Hashing Cost Factor -- The signup endpoint uses a bcrypt cost factor of 1, which is too weak and makes brute-forcing the hash cheap.
  - Root cause: const hashedPassword = await bcrypt.hash(password, 1);
  - Suggested fix: Increase the bcrypt cost factor to a value of at least 10 to enhance password hashing security.
- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-798) -- lib/mongodb.ts:6 -- Hardcoded Credentials -- A hardcoded MongoDB connection string with a fake but realistic credential is present in the code.
  - Root cause: const FALLBACK_MONGODB_URI = "mongodb+srv://finodil_admin:Sup3rSecretPass!@cluster0.abcde.mongodb.net/finodil";
  - Suggested fix: Remove the hardcoded credentials and use environment variables to store sensitive information securely.

## Moderate

- **[HIGH]** `SEC-JS-005` (CWE-79) -- app\login-and-signup\page.tsx:166 -- dangerouslySetInnerHTML bypasses React's default escaping; unsanitized HTML here is stored/DOM XSS.
  - Root cause: A dangerouslySetInnerHTML attribute was found at app\login-and-signup\page.tsx:166, rendering raw HTML without React's default escaping.
  - Suggested fix: Remove dangerouslySetInnerHTML and render the content as plain text/JSX, or sanitize the HTML through a trusted library (e.g. DOMPurify) before rendering it.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-532) -- app/api/auth/login/route.ts:18 -- Plaintext Password Logging -- The login endpoint logs the plaintext password, which can lead to sensitive information exposure if logs are accessed by unauthorized parties.
  - Root cause: console.log('Login attempt:', email, password);
  - Suggested fix: Remove or replace the console.log statement to prevent logging sensitive information.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-79) -- app/login-and-signup/page.tsx:102 -- Cross-Site Scripting (XSS) -- The error message is rendered using dangerouslySetInnerHTML, which can allow an attacker to inject malicious scripts if the error message includes user input or API responses.
  - Root cause: dangerouslySetInnerHTML={{ __html: error }}
  - Suggested fix: Replace dangerouslySetInnerHTML with plain text rendering to prevent XSS. For example, use {error} instead of {{ __html: error }}.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-798) -- models/LoginAndSignupData.ts:14 -- Password Storage Vulnerability -- The password field is stored in plaintext, which poses a risk of sensitive data exposure if the database is compromised.
  - Root cause: The password field is defined without any encryption or hashing.
  - Suggested fix: Hash the password using a strong hashing algorithm like bcrypt before storing it in the database. For example, use `bcrypt.hashSync(password, saltRounds)` to hash the password before saving it.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

AI model deep scan ran over 3 batch(es) of real source code (3 succeeded, 0 failed): 6 finding(s).