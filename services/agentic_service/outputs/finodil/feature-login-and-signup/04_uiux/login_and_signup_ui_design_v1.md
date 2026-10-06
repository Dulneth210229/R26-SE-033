# UI/UX Design: Login and Signup

> Review the attached page screenshots alongside this summary. The screenshots show the literal generated components -- there is no later regeneration step that could introduce drift from what you approve here.

---

## Page: Login Page

- **Route:** `/login`
- **Actors:** Guest, Registered User
- **Covers requirements:** FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, AC-001, AC-002, AC-003, AC-004, AC-005, AC-006
- **States:** idle, loading, error, success

### Components

- **LoginForm** (new)
  - Covers UI expectations: A clean, modern design with clear input fields and error messages
  - Why new: No existing component in the design system fits the specific requirements of this login form.
- **PasswordToggleButton** (new)
  - Covers UI expectations: A clean, modern design with clear input fields and error messages
  - Why new: No existing component in the design system fits the specific requirements of this password toggle button.
- **ForgotPasswordLink** (new)
  - Covers UI expectations: A clean, modern design with clear input fields and error messages
  - Why new: No existing component in the design system fits the specific requirements of this forgot password link.
- **SignupLink** (new)
  - Covers UI expectations: A clean, modern design with clear input fields and error messages
  - Why new: No existing component in the design system fits the specific requirements of this signup link.

---

## Page: Signup Page

- **Route:** `/signup`
- **Actors:** Guest
- **Covers requirements:** FR-009, FR-010, FR-011, FR-012, FR-013, FR-014, FR-015, AC-001, AC-002
- **States:** idle, loading, error, success

### Components

- **SignupForm** (new)
  - Covers UI expectations: A clean, modern design with clear input fields and error messages
  - Why new: No existing component in the design system fits the specific requirements of this signup form.
- **LoginLink** (new)
  - Covers UI expectations: A clean, modern design with clear input fields and error messages
  - Why new: No existing component in the design system fits the specific requirements of this login link.

---

## Page: User Profile Page

- **Route:** `/profile`
- **Actors:** Registered User
- **Covers requirements:** US-001, US-002
- **States:** idle, loading, error, success

### Components

- **UserProfileCard** (new)
  - Covers UI expectations: A clean, modern design with clear input fields and error messages
  - Why new: No existing component in the design system fits the specific requirements of this user profile card.
- **EditProfileButton** (new)
  - Covers UI expectations: A clean, modern design with clear input fields and error messages
  - Why new: No existing component in the design system fits the specific requirements of this edit profile button.

---

## Design System Impact

### New components introduced
- LoginForm
- PasswordToggleButton
- ForgotPasswordLink
- SignupLink
- SignupForm
- LoginLink
- UserProfileCard
- EditProfileButton

### New design tokens introduced
- `color.danger`: #B00020 -- This color is needed for error messages to stand out against the primary theme.
- `color.danger`: #B00020 -- This color is needed for error messages to stand out against the primary theme.
- `color.danger`: #B00020 -- This color is needed for error messages to stand out against the primary theme.
