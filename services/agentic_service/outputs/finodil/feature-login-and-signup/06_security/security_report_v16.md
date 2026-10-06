# Security Report -- Finodil / Login and Signup

Generated: 2026-08-25T13:31:12.772962+00:00
Scan type: **AI model deep scan**
Gate decision: **REVIEW**
Total findings: 6 (0 critical, 6 moderate, 0 warning)

## Moderate

- **[MEDIUM]** `SEC-JS-006` (CWE-915) -- app\api\auth\login\route.ts:39 -- Dynamic bracket property access keyed directly by a request-controlled parameter name (e.g. obj[req.query.sort]) is an object-injection / prototype-pollution-adjacent pattern; the accessor should be validated against an explicit allow-list of field names.
  - Root cause: A dynamic bracket property access (obj[key]) was found at app\api\auth\login\route.ts:39, using a request-controlled value as the property name.
  - Suggested fix: Validate the property name against an explicit allow-list of known-safe field names before using it to index the object.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-89) -- app/api/auth/login/route.ts:35 -- NoSQL Injection -- The `filter` object is not properly sanitized before being used in the database query, which could lead to NoSQL injection attacks.
  - Root cause: The `filter` object is directly merged into the query without proper validation or sanitization.
  - Suggested fix: Ensure that only allowed fields are included in the `filter` object and validate their values. For example, add a whitelist of allowed operators and types for each field.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-200) -- app/api/auth/login/route.ts:74 -- Sensitive Data Exposure -- The API response includes sensitive user information such as `id`, `name`, and `email` after successful login.
  - Root cause: The response includes user details that are not necessary for the client to know.
  - Suggested fix: Only return essential information in the API response. For example, remove `name` and `email` from the response if they are not needed by the client.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-200) -- app/api/auth/signup/route.ts:89 -- Sensitive Data Exposure -- The API response includes sensitive user information such as `id`, `name`, and `email` after successful signup.
  - Root cause: The response includes user details that are not necessary for the client to know.
  - Suggested fix: Only return essential information in the API response. For example, remove `name` and `email` from the response if they are not needed by the client.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-20) -- app/api/auth/login/route.ts:35 -- Security Misconfiguration -- The application does not have proper input validation for the `filter` object in the login route, which could lead to unexpected behavior or security issues.
  - Root cause: Lack of validation for the `filter` object before using it in the database query.
  - Suggested fix: Implement comprehensive input validation and sanitization for all user inputs, especially those used in database queries.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-203) -- models\LoginAndSignupData.ts:14 -- Password Storage Vulnerability -- The password field is stored in plaintext, which poses a risk of sensitive data exposure if the database is compromised.
  - Root cause: The password field is defined with type String and stored directly without any encryption or hashing.
  - Suggested fix: Hash the password using a strong cryptographic hash function before storing it in the database. For example, use bcrypt to hash the password.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

AI model deep scan ran over 3 batch(es) of real source code (3 succeeded, 0 failed): 5 finding(s).