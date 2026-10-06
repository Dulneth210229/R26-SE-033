# Security Report -- Finodil / Login and Signup

Generated: 2026-08-25T13:42:30.648214+00:00
Scan type: **AI model deep scan**
Gate decision: **FAIL**
Total findings: 9 (1 critical, 5 moderate, 3 warning)

## Critical

- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-798) -- models/LoginAndSignupData.ts:10 -- Password Stored in Plaintext -- The password field is stored in plaintext without any hashing or encryption, which poses a significant risk of exposing user passwords if the database is compromised.
  - Root cause: The password field does not have any hashing or encryption applied before being stored in the database.
  - Suggested fix: Implement a strong password-hashing algorithm (e.g., bcrypt, Argon2) to hash passwords before storing them in the database. Ensure that the salt is properly managed and rotated as needed.

## Moderate

- **[MEDIUM]** `SEC-JS-006` (CWE-915) -- app\api\auth\login\route.ts:39 -- Dynamic bracket property access keyed directly by a request-controlled parameter name (e.g. obj[req.query.sort]) is an object-injection / prototype-pollution-adjacent pattern; the accessor should be validated against an explicit allow-list of field names.
  - Root cause: A dynamic bracket property access (obj[key]) was found at app\api\auth\login\route.ts:39, using a request-controlled value as the property name.
  - Suggested fix: Validate the property name against an explicit allow-list of known-safe field names before using it to index the object.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-521) -- models/LoginAndSignupData.ts:13 -- Hardcoded Password Minimum Length -- The password field has a hardcoded minimum length of 6 characters, which may be considered weak and could potentially be bypassed by attackers.
  - Root cause: The 'minlength' property is set to a hardcoded value of 6 in the password field schema.
  - Suggested fix: Increase the minimum length requirement for passwords and consider implementing additional validation such as complexity requirements (e.g., including uppercase letters, numbers, and special characters).
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-89) -- app/api/auth/login/route.ts:35 -- NoSQL Injection -- The code does not validate the 'filter' object properly, allowing potential NoSQL injection attacks.
  - Root cause: The 'filter' object is directly used in the query without proper validation or sanitization.
  - Suggested fix: Validate and sanitize the 'filter' object to ensure only allowed fields are used in the query.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-200) -- app/api/auth/login/route.ts:75 -- Sensitive Data Exposure -- The code returns sensitive user data (id, name, email) in the API response after a successful login.
  - Root cause: The 'user' object is returned with sensitive fields in the API response.
  - Suggested fix: Remove or obfuscate sensitive user data from the API response.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-200) -- app/api/auth/signup/route.ts:98 -- Sensitive Data Exposure -- The code returns sensitive user data (id, name, email) in the API response after a successful signup.
  - Root cause: The 'newUser' object is returned with sensitive fields in the API response.
  - Suggested fix: Remove or obfuscate sensitive user data from the API response.

## Warning

- **[LOW]** `SEC-AI-DEEPSCAN` (CWE-312) -- app/api/auth/login/route.ts:69 -- Security Misconfiguration -- The code logs error messages that may leak internal details about the server.
  - Root cause: Error messages are logged with detailed information.
  - Suggested fix: Use generic error messages and avoid logging sensitive details.
- **[LOW]** `SEC-AI-DEEPSCAN` (CWE-312) -- app/api/auth/signup/route.ts:109 -- Security Misconfiguration -- The code logs error messages that may leak internal details about the server.
  - Root cause: Error messages are logged with detailed information.
  - Suggested fix: Use generic error messages and avoid logging sensitive details.
- **[LOW]** `SEC-AI-DEEPSCAN` (CWE-312) -- app/api/auth/logout/route.ts:13 -- Security Misconfiguration -- The code logs error messages that may leak internal details about the server.
  - Root cause: Error messages are logged with detailed information.
  - Suggested fix: Use generic error messages and avoid logging sensitive details.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

AI model deep scan ran over 3 batch(es) of real source code (3 succeeded, 0 failed): 8 finding(s).