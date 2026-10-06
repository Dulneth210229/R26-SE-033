# QA Report -- Retail Store / Add & List Items

Generated: 2026-08-31T10:58:26.829480+00:00
Framework: jest
Tests written: 8 (unit 1, integration 2, regression 5)
Result: 3 passed, 5 failed

## Test cases

- **[PASSED]** (unit) connectToDatabase() resolves without throwing when its required env var is unset -- targets `lib/mongodb.ts::connectToDatabase`
- **[PASSED]** (integration) GET app/api/items/route.ts is callable and does not crash on its own broken code -- targets `app/api/items/route.ts::GET`
- **[PASSED]** (integration) POST app/api/items/route.ts is callable and does not crash on its own broken code -- targets `app/api/items/route.ts::POST`
- **[FAILED]** (regression) AC-001: Given a user fills in name, price, quantity, and an image, when they submit the form, then a new item is created and appears in the list immediately. -- targets ``
  - ReferenceError: POST is not defined
  - Root cause: The test is trying to use 'POST' which is not defined. This could be due to missing import or incorrect usage of HTTP method.
  - Recommendation: Ensure that the 'POST' method is correctly imported from an appropriate library, such as 'axios' or 'fetch'.
- **[FAILED]** (regression) AC-002: Given a user submits the form with a missing required field (name, price, or quantity) or a negative price/quantity, when they submit, then the form shows a clear validation error and does not create the item. -- targets ``
  - ReferenceError: POST is not defined
  - Root cause: The test is trying to use 'POST' which is not defined. This could be due to missing import or incorrect usage of HTTP method.
  - Recommendation: Ensure that the 'POST' method is correctly imported from an appropriate library, such as 'axios' or 'fetch'.
- **[FAILED]** (regression) AC-003: Given a user uploads a file that isn't an image or exceeds the size limit, when they submit, then the form shows a clear error and does not create the item. -- targets ``
  - ReferenceError: POST is not defined
  - Root cause: The test is trying to use 'POST' which is not defined. This could be due to missing import or incorrect usage of HTTP method.
  - Recommendation: Ensure that the 'POST' method is correctly imported from an appropriate library, such as 'axios' or 'fetch'.
- **[FAILED]** (regression) AC-004: Given no items have been added yet, when the list is opened, then a clear 'No items added yet' empty state is shown instead of a blank page. -- targets ``
  - ReferenceError: GET is not defined
  - Root cause: The test is trying to use 'GET' which is not defined. This could be due to missing import or incorrect usage of HTTP method.
  - Recommendation: Ensure that the 'GET' method is correctly imported from an appropriate library, such as 'axios' or 'fetch'.
- **[FAILED]** (regression) AC-005: Given items exist, when the list is opened, then every item's image, name, description, price, and quantity are displayed correctly. -- targets ``
  - ReferenceError: GET is not defined
  - Root cause: The test is trying to use 'GET' which is not defined. This could be due to missing import or incorrect usage of HTTP method.
  - Recommendation: Ensure that the 'GET' method is correctly imported from an appropriate library, such as 'axios' or 'fetch'.

## Out of scope for this pass

- `app/add-list-items/items/page.tsx`
- `app/add-list-items/page.tsx`
- `app/layout.tsx`
- `app/page.tsx`
- `components/PreviewRouteAnnouncer.tsx`