# Merge Report: Login and Signup

**Verification:** PASSED
**Coding attempts used:** 2

> **This verification ran against a REAL, human-provided database connection**, not the default seed-data fallback -- review any data writes accordingly.

## Verification steps
- **next.config.mjs integrity**: passed
- **npm install**: passed
- **next build**: passed
- **server boot (next start + /api/health)**: passed
- **npm run test (root)**: skipped
- **endpoint route coverage**: passed
- **database null-guard coverage**: passed
- **schema/form field coverage**: passed
- **page reachability**: passed
- **home page render**: passed
- **feature page render**: info
  ```
  All 1 feature page(s) rendered cleanly:
  - /login-and-signup: /login-and-signup responded with HTTP 200 and no JS errors.
  ```
- **CRUD functional smoke test**: info
  ```
  
  - (n/a): skipped -- Could not confidently synthesize a create payload from any planned form's own state -- skipping the functional check for this attempt.
  ```
- **placeholder-stub scan**: info
  ```
  None found.
  ```
- **database fallback quality scan**: info
  ```
  These null-guard branches look like a bare empty/error response rather than seed data (does not fail verification, review before approving):
  - app/api/auth/login/route.ts:16: { status: 400 }
  - app/api/auth/login/route.ts:27: { status: 503 }
  - app/api/auth/login/route.ts:52: { status: 401 }
  - app/api/auth/login/route.ts:61: { status: 401 }
  - app/api/auth/login/route.ts:82: { status: 500 }
  - app/api/auth/signup/route.ts:16: { status: 400 }
  - app/api/auth/signup/route.ts:25: { status: 400 }
  - app/api/auth/signup/route.ts:33: { status: 400 }
  - app/api/auth/signup/route.ts:44: { status: 503 }
  - app/api/auth/signup/route.ts:53: { status: 409 }
  - app/api/auth/signup/route.ts:82: { status: 500 }
  ```
- **request relevance scan**: info
  ```
  30/61 distinctive request word(s) found in the touched files.
  ```
- **ui_expectations coverage**: info
  ```
  No SRS ui_expectations available to check against.
  ```
- **security finding file coverage**: info
  ```
  All 2 file(s) named in the security report were touched by this attempt.
  ```

## Files changed
### Modified
- `app/api/auth/login/route.ts`
- `app/api/auth/signup/route.ts`

## Detailed Code Changes (Line-by-Line Diff)
```diff
diff --git a/app/api/auth/login/route.ts b/app/api/auth/login/route.ts
index 59320e7..204c657 100644
--- a/app/api/auth/login/route.ts
+++ b/app/api/auth/login/route.ts
@@ -17,9 +17,6 @@ export async function POST(request: Request) {
       );
     }
 
-    // DELIBERATE, AUTHORIZED TEST VULNERABILITY (CWE-532) -- logs the plaintext password.
-    console.log("Login attempt:", email, password);
-
     const db = await connectToDatabase();
     
     // If no database connection, return seed data (fallback behavior)
@@ -31,10 +28,24 @@ export async function POST(request: Request) {
       );
     }
 
-    // DELIBERATE, AUTHORIZED TEST VULNERABILITY (CWE-943) -- merges a client-supplied `filter`
-    // object directly into the MongoDB query, letting a caller inject arbitrary query operators
-    // (e.g. {"password": {"$ne": null}}) alongside the email lookup.
-    const user = await LoginAndSignupData.findOne({ email, ...filter });
+    // Sanitize filter object to prevent NoSQL injection
+    // Only allow specific allowed fields to be used in the query
+    const allowedFields = ['email']; // Add other allowed fields here if needed
+    let sanitizedFilter: { [key: string]: any } = {};
+    
+    if (filter && typeof filter === 'object') {
+      for (const key in filter) {
+        if (allowedFields.includes(key)) {
+          sanitizedFilter[key] = filter[key];
+        }
+      }
+    }
+
+    // Use sanitized filter in the query
+    const user = await LoginAndSignupData.findOne({ email, ...sanitizedFilter });
+    
+    // Remove plaintext password logging
+    // console.log('Login attempt:', email, password);
     if (!user) {
       return NextResponse.json(
         { error: "Invalid email or password" },
diff --git a/app/api/auth/signup/route.ts b/app/api/auth/signup/route.ts
index e476d79..46e9b60 100644
--- a/app/api/auth/signup/route.ts
+++ b/app/api/auth/signup/route.ts
@@ -54,9 +54,8 @@ export async function POST(request: Request) {
       );
     }
 
-    // DELIBERATE, AUTHORIZED TEST VULNERABILITY (CWE-916) -- a bcrypt cost factor of 1 is far too
-    // weak (makes brute-forcing the hash cheap); a real value should be >= 10.
-    const hashedPassword = await bcrypt.hash(password, 1);
+    // Increase bcrypt cost factor from 1 to 12 to strengthen password hashing
+    const hashedPassword = await bcrypt.hash(password, 12);
 
     // Create new user
     const newUser = new LoginAndSignupData({
```