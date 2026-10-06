"""
Unit tests for security_finding_coverage_checker.py -- the new, deterministic, info-only
verify() step that flags when a security-driven revision's own touched files don't cover every
file the Security Agent's report actually named.

REAL_SECURITY_REVISION_COMMENT below is the exact, real revision_comment captured from the live
Finodil "Login and Signup" feature's event log (feature_917b691e) -- 7 findings across 4 real
files, mixing backslash and forward-slash separators exactly as the real report produced them.
"""

from app.agents.coder_agent.security_finding_coverage_checker import (
    check_security_finding_file_coverage,
)

REAL_SECURITY_REVISION_COMMENT = r"""Fix the following security findings reported by the Security Agent:

[CRITICAL] lib\mongodb.ts:6 -- MongoDB connection string with an embedded, hardcoded credential (CWE-798)
  Root cause: A hardcoded secret literal (mongodb connection string with an embedded, hardcoded credential) was found directly in source at lib\mongodb.ts:6.
  Suggested fix: Move this value to `.env.local` (gitignored) and read it via `process.env.X` at runtime; rotate the exposed credential/key immediately, since it may already be compromised.
[CRITICAL] app/api/auth/login/route.ts:35 -- NoSQL Injection via Query Parameters -- The login endpoint merges a client-supplied `filter` object directly into the MongoDB query, allowing for NoSQL injection attacks. (CWE-943)
  Root cause: const user = await LoginAndSignupData.findOne({ email, ...filter });
  Suggested fix: Sanitize or validate the `filter` object to prevent injection attacks.
[MODERATE] app\login-and-signup\page.tsx:166 -- dangerouslySetInnerHTML bypasses React's default escaping; unsanitized HTML here is stored/DOM XSS. (CWE-79)
  Root cause: A dangerouslySetInnerHTML attribute was found at app\login-and-signup\page.tsx:166, rendering raw HTML without React's default escaping.
  Suggested fix: Remove dangerouslySetInnerHTML and render the content as plain text/JSX, or sanitize the HTML through a trusted library (e.g. DOMPurify) before rendering it.
[MODERATE] app/api/auth/login/route.ts:17 -- Plaintext Password Logging -- The login endpoint logs the plaintext password to the console, which can lead to sensitive information exposure. (CWE-532)
  Root cause: console.log('Login attempt:', email, password);
  Suggested fix: Remove or replace the line that logs the plaintext password.
[MODERATE] app/api/auth/signup/route.ts:54 -- Weak Bcrypt Cost Factor -- The signup endpoint uses a bcrypt cost factor of 1, which is too weak and makes brute-forcing the hash cheap. (CWE-916)
  Root cause: const hashedPassword = await bcrypt.hash(password, 1);
  Suggested fix: Increase the bcrypt cost factor to a value of at least 10.
"""

# The REAL touched_paths from the actual v5 Coder Agent attempt against this exact comment --
# confirmed live that this attempt only ever touched 2 of the 4 files the report named.
REAL_V5_TOUCHED_PATHS = ["lib/mongodb.ts", "app/login-and-signup/page.tsx"]

# What a fully-covering attempt's touched_paths would look like, for contrast.
FULLY_COVERING_TOUCHED_PATHS = [
    "lib/mongodb.ts",
    "app/login-and-signup/page.tsx",
    "app/api/auth/login/route.ts",
    "app/api/auth/signup/route.ts",
]


def test_non_security_comment_produces_no_step():
    assert check_security_finding_file_coverage("Add a logout button", ["app/page.tsx"]) is None


def test_none_or_empty_comment_produces_no_step():
    assert check_security_finding_file_coverage(None, ["app/page.tsx"]) is None
    assert check_security_finding_file_coverage("", ["app/page.tsx"]) is None


def test_real_partial_attempt_flags_the_two_untouched_files():
    step = check_security_finding_file_coverage(REAL_SECURITY_REVISION_COMMENT, REAL_V5_TOUCHED_PATHS)
    assert step["name"] == "security finding file coverage"
    assert step["status"] == "info"
    assert "app/api/auth/login/route.ts" in step["output"]
    assert "app/api/auth/signup/route.ts" in step["output"]
    # The two files this real attempt DID touch must not be reported as missing.
    missing_section = step["output"].split(": ", 1)[1]
    assert "mongodb.ts" not in missing_section
    assert "page.tsx" not in missing_section


def test_real_fully_covering_attempt_reports_all_covered():
    step = check_security_finding_file_coverage(REAL_SECURITY_REVISION_COMMENT, FULLY_COVERING_TOUCHED_PATHS)
    assert step["status"] == "info"
    assert "All 4 file(s)" in step["output"]


def test_security_marker_present_but_no_extractable_file_tokens():
    step = check_security_finding_file_coverage("[CRITICAL] something is wrong here (CWE-1)", [])
    assert step["status"] == "info"
    assert "no file names could be extracted" in step["output"]


def test_never_affects_passed_shape():
    # This step is info-only by construction -- confirm the returned dict never carries a
    # "failed" status regardless of how badly the coverage gap looks.
    step = check_security_finding_file_coverage(REAL_SECURITY_REVISION_COMMENT, [])
    assert step["status"] == "info"
