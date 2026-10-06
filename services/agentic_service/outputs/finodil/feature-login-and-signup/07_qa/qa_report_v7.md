# QA Report -- Finodil / Login and Signup

Generated: 2026-08-28T15:21:10.847192+00:00
Framework: jest
Tests written: 3 (unit 1, integration 0, regression 2)
Result: 1 passed, 2 failed, 0 skipped

## Test cases

- **[PASSED]** (unit) connectToDatabase() resolves without throwing when its required env var is unset -- targets `lib/mongodb.ts::connectToDatabase`
- **[FAILED]** (regression) AC-003: Given valid login credentials, when the user submits the login form, then they are logged in within 3 seconds and redirected to the sample home page, with the nav bar showing their logged-in state -- targets ``
  - ReferenceError: POST is not defined
  - Root cause: The test is trying to use 'POST' but it is not defined. This could be due to missing import or incorrect usage.
  - Recommendation: Ensure that the 'POST' method is correctly imported from a suitable module, such as 'axios' or 'fetch'. For example, if using axios, add `import axios from 'axios';` at the top of your test file.
- **[FAILED]** (regression) AC-004: Given invalid login credentials (wrong email or wrong password), when the user submits the login form, then they see a generic 'Invalid email or password' error and remain on the login page -- targets ``
  - ReferenceError: POST is not defined
  - Root cause: The test is trying to use 'POST' but it is not defined. This could be due to missing import or incorrect usage.
  - Recommendation: Ensure that the 'POST' method is correctly imported from a suitable module, such as 'axios' or 'fetch'. For example, if using axios, add `import axios from 'axios';` at the top of your test file.

## Out of scope for this pass

- `app/layout.tsx`
- `app/login-and-signup/page.tsx`
- `app/page.tsx`
- `components/PreviewRouteAnnouncer.tsx`