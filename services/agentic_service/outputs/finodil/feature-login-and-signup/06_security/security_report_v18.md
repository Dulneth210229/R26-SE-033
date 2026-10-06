# Security Report -- Finodil / Login and Signup

Generated: 2026-08-30T10:44:49.284017+00:00
Scan type: **AI model deep scan**
Gate decision: **REVIEW**
Total findings: 4 (0 critical, 4 moderate, 0 warning)

## Moderate

- **[MEDIUM]** `SEC-JS-006` (CWE-915) -- app\api\auth\login\route.ts:39 -- Dynamic bracket property access keyed directly by a request-controlled parameter name (e.g. obj[req.query.sort]) is an object-injection / prototype-pollution-adjacent pattern; the accessor should be validated against an explicit allow-list of field names.
  - Root cause: A dynamic bracket property access (obj[key]) was found at app\api\auth\login\route.ts:39, using a request-controlled value as the property name.
  - Suggested fix: Validate the property name against an explicit allow-list of known-safe field names before using it to index the object.
- **[HIGH]** `SEC-AI-DEEPSCAN` (CWE-312) -- lib/api/loginAndSignup.ts:4 -- Broken Authentication - Weak Password Handling -- The password is being sent in plain text during the signup and login processes. This can lead to interception of credentials during transmission.
  - Root cause: The password is being sent in plain text in the request body.
  - Suggested fix: Use HTTPS to encrypt the data in transit and consider hashing the password before sending it to the server.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-20) -- lib/api/loginAndSignup.ts:4 -- Security Misconfiguration - Missing Input Validation -- The signup and login functions do not validate the input data before sending it to the server. This can lead to unexpected behavior or security issues.
  - Root cause: The input data is not being validated before being sent to the server.
  - Suggested fix: Add input validation to ensure that the name, email, and password fields meet the expected criteria before sending the request.
- **[MEDIUM]** `SEC-AI-DEEPSCAN` (CWE-209) -- lib/api/loginAndSignup.ts:13 -- Security Misconfiguration - Missing Error Handling -- The error messages returned by the server are not being sanitized. This can leak sensitive information about the server's internal state.
  - Root cause: The error messages are being returned directly to the client.
  - Suggested fix: Sanitize the error messages before returning them to the client to avoid leaking sensitive information.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

AI model deep scan ran over 3 batch(es) of real source code (3 succeeded, 0 failed): 3 finding(s).