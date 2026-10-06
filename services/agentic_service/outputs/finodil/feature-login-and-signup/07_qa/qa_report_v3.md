# QA Report -- Finodil / Login and Signup

Generated: 2026-08-26T15:55:43.669139+00:00
Framework: jest
Tests written: 3 (unit 1, integration 0, regression 2)
Result: 0 passed, 0 failed, 0 skipped

## Test cases

- **[SKIPPED]** (unit) connectToDatabase() resolves without throwing when its required env var is unset -- targets `lib/mongodb.ts::connectToDatabase`
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.
- **[SKIPPED]** (regression) AC-003: Given valid login credentials, when the user submits the login form, then they are logged in within 3 seconds and redirected to the sample home page, with the nav bar showing their logged-in state -- targets ``
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.
- **[SKIPPED]** (regression) AC-004: Given invalid login credentials (wrong email or wrong password), when the user submits the login form, then they see a generic 'Invalid email or password' error and remain on the login page -- targets ``
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.

## Out of scope for this pass

- `app/layout.tsx`
- `app/login-and-signup/page.tsx`
- `app/page.tsx`
- `components/PreviewRouteAnnouncer.tsx`