# Security Report -- Finodil / Login and Signup

Generated: 2026-08-25T13:20:02.943646+00:00
Scan type: **AI model deep scan**
Gate decision: **REVIEW**
Total findings: 6 (0 critical, 3 moderate, 3 warning)

## Moderate

- **[MEDIUM]** `SEC-JS-006` (CWE-915) -- app\api\auth\login\route.ts:39 -- Dynamic bracket property access keyed directly by a request-controlled parameter name (e.g. obj[req.query.sort]) is an object-injection / prototype-pollution-adjacent pattern; the accessor should be validated against an explicit allow-list of field names.
  - Root cause: A dynamic bracket property access (obj[key]) was found at app\api\auth\login\route.ts:39, using a request-controlled value as the property name.
  - Suggested fix: Validate the property name against an explicit allow-list of known-safe field names before using it to index the object.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-89) -- app/api/auth/login/route.ts:31 -- NoSQL Injection -- The code allows user-controlled input to be used in a database query without proper validation, which can lead to NoSQL injection attacks.
  - Root cause: The `filter` object is directly used in the query without sanitization, allowing user-controlled fields to be included.
  - Suggested fix: Sanitize and validate all user inputs before using them in database queries. Only allow specific fields that are necessary for the query.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-200) -- app/api/auth/login/route.ts:71 -- Sensitive Data Exposure -- The code returns sensitive user information (id, name, email) in the API response after a successful login.
  - Root cause: The `user` object, which contains sensitive information, is returned in the API response.
  - Suggested fix: Only return necessary user information that does not include sensitive data like passwords or other personal details.

## Warning

- **[LOW]** `SEC-AI-DEEPSCAN` (CWE-312) -- app/api/auth/login/route.ts:65 -- Security Misconfiguration -- The code logs error messages to the console, which can leak internal information about the application.
  - Root cause: The `console.error` statement logs error messages to the console, which can be accessed by attackers.
  - Suggested fix: Avoid logging sensitive information in error messages. Use a structured logging system that does not expose internal details.
- **[LOW]** `SEC-AI-DEEPSCAN` (CWE-312) -- app/api/auth/signup/route.ts:75 -- Security Misconfiguration -- The code logs error messages to the console, which can leak internal information about the application.
  - Root cause: The `console.error` statement logs error messages to the console, which can be accessed by attackers.
  - Suggested fix: Avoid logging sensitive information in error messages. Use a structured logging system that does not expose internal details.
- **[LOW]** `SEC-AI-DEEPSCAN` (CWE-312) -- app/api/auth/logout/route.ts:10 -- Security Misconfiguration -- The code logs error messages to the console, which can leak internal information about the application.
  - Root cause: The `console.error` statement logs error messages to the console, which can be accessed by attackers.
  - Suggested fix: Avoid logging sensitive information in error messages. Use a structured logging system that does not expose internal details.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

AI model deep scan ran over 3 batch(es) of real source code (3 succeeded, 0 failed): 5 finding(s).