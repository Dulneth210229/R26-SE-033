# QA Report -- Finodil / Login and Signup

Generated: 2026-08-26T16:31:21.502767+00:00
Framework: jest
Tests written: 7 (unit 1, integration 0, regression 6)
Result: 0 passed, 0 failed, 7 skipped

## Test cases

- **[SKIPPED]** (unit) connectToDatabase() resolves without throwing when its required env var is unset -- targets `lib/mongodb.ts::connectToDatabase`
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.
- **[SKIPPED]** (regression) AC-001: Given a new, unused email and a valid password, when the user submits the signup form, then their account is created, their password is hashed before storage, and they are automatically logged in and redirected to the home page -- targets ``
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.
- **[SKIPPED]** (regression) AC-002: Given an email that's already registered, when the user submits the signup form, then they see a clear 'An account with this email already exists' error and remain on the signup page -- targets ``
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.
- **[SKIPPED]** (regression) AC-003: Given valid login credentials, when the user submits the login form, then they are logged in within 3 seconds and redirected to the sample home page, with the nav bar showing their logged-in state -- targets ``
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.
- **[SKIPPED]** (regression) AC-004: Given invalid login credentials (wrong email or wrong password), when the user submits the login form, then they see a generic 'Invalid email or password' error and remain on the login page -- targets ``
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.
- **[SKIPPED]** (regression) AC-005: Given a logged-in user, when they click 'Logout', then their session ends and they are redirected to the login page -- targets ``
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.
- **[SKIPPED]** (regression) AC-006: Given a logged-in user, when they refresh the page, then they remain logged in (session persists) -- targets ``
  - This test file did not produce a matching result -- it may have failed to load/parse; see stderr below.

## Out of scope for this pass

- `app/layout.tsx`
- `app/login-and-signup/page.tsx`
- `app/page.tsx`
- `components/PreviewRouteAnnouncer.tsx`