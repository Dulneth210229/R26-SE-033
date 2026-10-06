# Security Report -- Deep Scan Test / Deep Scan Test Feature

Generated: 2026-08-31T09:35:59.447086+00:00
Scan type: **AI model deep scan**
Gate decision: **FAIL**
Total findings: 1 (1 critical, 0 moderate, 0 warning)

## Critical

- **[CRITICAL]** `SEC-AI-DEEPSCAN` (CWE-943) -- app/api/auth/login/route.ts:20 -- NoSQL injection -- client filter merged into query.
  - Root cause: req.body fields are spread directly into the Mongoose query filter.
  - Suggested fix: Only allow a fixed set of known-safe query fields.

## Dependency scan

npm audit exit code: 0
Ran offline (sandbox has no outbound network to the npm advisory endpoint): True
Dependency summary: {}

## LLM review layer

AI model deep scan ran over 1 batch(es)...