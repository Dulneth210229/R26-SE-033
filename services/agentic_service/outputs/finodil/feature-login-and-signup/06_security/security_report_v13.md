# Security Report -- Finodil / Login and Signup

Generated: 2026-08-25T09:58:35.554393+00:00
Scan type: **Standard scan**
Gate decision: **REVIEW**
Total findings: 2 (0 critical, 2 moderate, 0 warning)

## Moderate

- **[MEDIUM]** `SEC-JS-006` (CWE-915) -- app\api\auth\login\route.ts:39 -- Dynamic bracket property access keyed directly by a request-controlled parameter name (e.g. obj[req.query.sort]) is an object-injection / prototype-pollution-adjacent pattern; the accessor should be validated against an explicit allow-list of field names.
  - Root cause: A dynamic bracket property access (obj[key]) was found at app\api\auth\login\route.ts:39, using a request-controlled value as the property name.
  - Suggested fix: Validate the property name against an explicit allow-list of known-safe field names before using it to index the object.
- **[HIGH]** `SEC-LLM-REVIEW` (CWE-787) -- app\api\auth\login\route.ts:39 -- Potential Prototype Pollution via Dynamic Property Access -- The use of dynamic bracket property access with a request-controlled parameter can lead to prototype pollution, where malicious input could modify the Object.prototype. This can be exploited to inject arbitrary properties into objects, potentially leading to security vulnerabilities.
  - Root cause: The code uses obj[req.query.sort] without validating the 'sort' parameter against an allow-list of field names.
  - Suggested fix: Validate the 'sort' parameter against a predefined list of allowed field names before using it in dynamic property access. For example, use a whitelist to ensure only expected properties are accessed.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {'info': 0, 'low': 0, 'moderate': 0, 'high': 0, 'critical': 0, 'total': 0}

## LLM review layer

LLM review layer ran successfully: 1 additional finding(s).