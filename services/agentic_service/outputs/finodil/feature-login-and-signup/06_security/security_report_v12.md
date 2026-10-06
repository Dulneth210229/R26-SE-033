# Security Report -- Finodil / Login and Signup

Generated: 2026-08-25T07:52:45.679041+00:00
Scan type: **AI model deep scan**
Gate decision: **FAIL**
Total findings: 3 (2 critical, 1 moderate, 0 warning)

## Critical

- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-943) -- app/api/auth/login/route.ts:27 -- NoSQL Injection via Query Parameters -- The code merges user-supplied `filter` object directly into the MongoDB query, allowing for NoSQL injection attacks.
  - Root cause: const user = await LoginAndSignupData.findOne({ email, ...filter });
  - Suggested fix: Sanitize and validate the `filter` object to prevent injection attacks.
- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-916) -- app/api/auth/signup/route.ts:42 -- Weak Password Hashing Cost Factor -- The bcrypt cost factor is set to 1, which is too weak and makes brute-forcing the hash cheap.
  - Root cause: const hashedPassword = await bcrypt.hash(password, 1);
  - Suggested fix: Increase the cost factor to a value of at least 10.

## Moderate

- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-532) -- app/api/auth/login/route.ts:14 -- Plaintext Password Logging -- The code logs the plaintext password in the console, which can lead to sensitive information exposure.
  - Root cause: console.log('Login attempt:', email, password);
  - Suggested fix: Remove or replace the line with a non-sensitive logging statement.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

AI model deep scan ran over 2 batch(es) of real source code (2 succeeded, 0 failed): 3 finding(s).