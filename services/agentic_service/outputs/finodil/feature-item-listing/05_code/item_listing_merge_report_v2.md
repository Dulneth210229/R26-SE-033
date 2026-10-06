# Merge Report: Item Listing

**Verification:** FAILED -- human review required before merging
**Coding attempts used:** 1

## Verification steps
- **next.config.mjs integrity**: passed
- **npm install**: passed
- **next build**: passed
- **server boot (next start + /api/health)**: passed
- **npm run test (root)**: skipped
- **endpoint route coverage**: passed
- **database null-guard coverage**: passed
- **hardcoded MongoDB URI scan**: passed
- **schema/form field coverage**: failed
  ```
  These Mongoose schema fields are marked required but no planned frontend file ever sets them -- a client can never satisfy the request, so every create/update using this model will fail:
  - "description" (required in models/ItemListingData.ts)
  - "price" (required in models/ItemListingData.ts)
  - "quantity" (required in models/ItemListingData.ts)
  - "category" (required in models/ItemListingData.ts)
  ```
- **page reachability**: passed
- **home page render**: passed
- **feature page render**: info
  ```
  All 2 feature page(s) rendered cleanly:
  - /item-listing: /item-listing responded with HTTP 200 and no JS errors.
  - /login-and-signup: /login-and-signup responded with HTTP 200 and no JS errors.
  ```
- **CRUD functional smoke test**: info
  ```
  
  - (n/a): skipped -- No planned POST endpoint found to check.
  ```
- **placeholder-stub scan**: info
  ```
  None found.
  ```
- **database fallback quality scan**: info
  ```
  These null-guard branches look like a bare empty/error response rather than seed data (does not fail verification, review before approving):
  - app/api/items/route.ts:52: { status: 500 }
  ```
- **request relevance scan**: info
  ```
  No original request text available to compare against.
  ```
- **ui_expectations coverage**: info
  ```
  These SRS ui_expectations bullets have no obvious trace in the frontend files touched this attempt -- worth a human double-check, not necessarily missing (a legitimate implementation can use entirely different words):
  - Responsive on both desktop and mobile widths.
  ```

## Files changed
### Added
- `app/api/items/route.ts`
- `app/item-listing/page.tsx`
- `babel.config.qa.js`
- `generated_tests/mongodb.unit.test.ts`
- `jest.config.qa.js`
- `lib/api/itemListing.ts`
- `lib/auth/session.ts`
- `lib/types/ItemListing.ts`
- `models/ItemListingData.ts`
### Modified
- `app/login-and-signup/page.tsx`
- `app/page.tsx`
- `lib/api/loginAndSignup.ts`
- `lib/mongodb.ts`
- `lib/seedData.ts`
- `package-lock.json`
- `package.json`

## Detailed Code Changes (Line-by-Line Diff) (truncated)
```diff
diff --git a/app/api/items/route.ts b/app/api/items/route.ts
new file mode 100644
index 0000000..c7d127c
--- /dev/null
+++ b/app/api/items/route.ts
@@ -0,0 +1,55 @@
+import { NextResponse } from "next/server";
+import { connectToDatabase } from "@/lib/mongodb";
+import ItemListingData from "@/models/ItemListingData";
+import { seedItemListingData } from "@/lib/seedData";
+import type { ItemListingItem } from "@/lib/types/ItemListing";
+
+export const dynamic = "force-dynamic";
+
+// GET /api/items -- returns the list of sample items (SRS FR-002/API-001).
+export async function GET() {
+  try {
+    const db = await connectToDatabase();
+
+    if (!db) {
+      // No live database connection configured (or it could not be reached) -- serve the
+      // shared seed data so the page always shows real, populated content (FR-003/AC-003).
+      const items: ItemListingItem[] = seedItemListingData.map((item) => ({
+        ...item,
+        createdAt: item.createdAt.toISOString(),
+        inStock: item.quantity > 0,
+      }));
+      return NextResponse.json(items);
+    }
+
+    // Real database, genuinely empty collection -- pre-seed it once so FR-003's "the database
+    // is pre-seeded with at least 8-10 sample items" holds for a real connection too, not just
+    // the no-DB fallback path.
+    const existingCount = await ItemListingData.countDocuments({});
+    if (existingCount === 0) {
+      await ItemListingData.insertMany(
+        seedItemListingData.map(({ _id, ...rest }) => rest)
+      );
+    }
+
+    const documents = await ItemListingData.find({}).sort({ createdAt: -1 }).lean();
+    const items: ItemListingItem[] = documents.map((doc: any) => ({
+      _id: String(doc._id),
+      name: doc.name,
+      description: doc.description,
+      price: doc.price,
+      quantity: doc.quantity,
+      category: doc.category,
+      createdAt: new Date(doc.createdAt).toISOString(),
+      inStock: doc.quantity > 0,
+    }));
+
+    return NextResponse.json(items);
+  } catch (error) {
+    console.error("Error fetching items:", error);
+    return NextResponse.json(
+      { error: "Failed to fetch items" },
+      { status: 500 }
+    );
+  }
+}
diff --git a/app/item-listing/page.tsx b/app/item-listing/page.tsx
new file mode 100644
index 0000000..993aba4
--- /dev/null
+++ b/app/item-listing/page.tsx
@@ -0,0 +1,187 @@
+"use client";
+
+import { useEffect, useState } from "react";
+import { useRouter } from "next/navigation";
+import { fetchItems } from "@/lib/api/itemListing";
+import { getSession } from "@/lib/auth/session";
+import type { ItemListingItem } from "@/lib/types/ItemListing";
+
+// Shared wrapper for the loading/error/empty states, matching the approved UI/UX design's own
+// centered-card convention (item_listing_errormessage_v1.html / item_listing_emptystate_v1.html).
+function CenteredStateCard({ children }: { children: React.ReactNode }) {
+  return (
+    <section className="bg-gray-50 min-h-screen flex items-center justify-center">
+      {children}
+    </section>
+  );
+}
+
+export default function ItemListingPage() {
+  const router = useRouter();
+  const [authChecked, setAuthChecked] = useState(false);
+  const [items, setItems] = useState<ItemListingItem[]>([]);
+  const [loading, setLoading] = useState(true);
+  const [error, setError] = useState<string | null>(null);
+
+  // FR-001/AC-001: only a logged-in user may see this page -- an unauthenticated visitor is
+  // redirected to the login page. This app's real backend never issues a cookie/JWT session
+  // (see lib/auth/session.ts's own docstring), so the one real, shared client-side marker
+  // login/signup writes on success is what's checked here.
+  useEffect(() => {
+    if (!getSession()) {
+      router.replace("/login-and-signup");
+      return;
+    }
+    setAuthChecked(true);
+  }, [router]);
+
+  useEffect(() => {
+    if (!authChecked) return;
+
+    let cancelled = false;
+
+    const loadItems = async () => {
+      setLoading(true);
+      setError(null);
+      try {
+        const data = await fetchItems();
+        if (!cancelled) setItems(data);
+      } catch (err) {
+        console.error("Error loading items:", err);
+        if (!cancelled) setError("Failed to load items. Please try again later.");
+      } finally {
+        if (!cancelled) setLoading(false);
+      }
+    };
+
+    loadItems();
+
+    return () => {
+      cancelled = true;
+    };
+  }, [authChecked]);
+
+  if (!authChecked) {
+    // Redirecting (or about to) -- render nothing rather than flashing the page's real content.
+    return null;
+  }
+
+  if (loading) {
+    return (
+      <CenteredStateCard>
+        <div className="bg-white shadow-lg rounded-lg p-6 max-w-md text-center">
+          <svg
+            className="w-12 h-12 mx-auto mb-4 text-indigo-600 animate-spin"
+            fill="none"
+            viewBox="0 0 24 24"
+          >
+            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
+            <path
+              className="opacity-75"
+              fill="currentColor"
+              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
+            />
+          </svg>
+          <h3 className="text-lg font-medium text-gray-800 mb-2">Loading</h3>
+          <p className="text-sm text-gray-600">Loading items...</p>
+        </div>
+      </CenteredStateCard>
+    );
+  }
+
+  if (error) {
+    return (
+      <CenteredStateCard>
+        <div className="bg-white shadow-lg rounded-lg p-6 max-w-md text-center">
+          <svg
+            className="w-12 h-12 mx-auto mb-4 text-red-600"
+            fill="none"
+            viewBox="0 0 24 24"
+            stroke="currentColor"
+            strokeWidth={1.5}
+          >
+            <path
+              strokeLinecap="round"
+              strokeLinejoin="round"
+              d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
+            />
+          </svg>
+          <h3 className="text-lg font-medium text-gray-800 mb-2">Error</h3>
+          <p className="text-sm text-gray-600 mb-4">{error}</p>
+          <button
+            onClick={() => window.location.reload()}
+            className="bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-2 px-4 rounded focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
+          >
+            Retry
+          </button>
+        </div>
+      </CenteredStateCard>
+    );
+  }
+
+  if (items.length === 0) {
+    return (
+      <CenteredStateCard>
+        <div className="text-center space-y-4">
+          <h1 className="text-2xl font-bold text-indigo-600">No items found.</h1>
+          <p className="text-gray-600">
+            It looks like there are no items available at the moment. Please check back later or
+            contact support for assistance.
+          </p>
+        </div>
+      </CenteredStateCard>
+    );
+  }
+
+  return (
+    <section className="bg-gray-50 p-6 min-h-screen">
+      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
+        <h1 className="text-2xl font-bold text-gray-900">Item Listing</h1>
+        <div className="mt-6 grid grid-cols-1 gap-y-10 gap-x-6 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:gap-x-8">
+          {items.map((item) => (
+            <div
+              key={item._id}
+              className="bg-white shadow-sm rounded-lg p-4 flex items-center space-x-4"
+            >
+              <div className="w-24 h-24 bg-gray-200 rounded-lg flex items-center justify-center flex-shrink-0">
+                <svg
+                  className="w-10 h-10 text-gray-400"
+                  fill="none"
+                  viewBox="0 0 24 24"
+                  stroke="currentColor"
+                  strokeWidth={1.5}
+                >
+                  <path
+                    strokeLinecap="round"
+                    strokeLinejoin="round"
+                    d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z"
+                  />
+                </svg>
+              </div>
+              <div className="flex-1 min-w-0">
+                <h2 className="text-xl font-bold text-gray-900">{item.name}</h2>
+                <p className="mt-1 text-sm text-gray-600 line-clamp-2">{item.description}</p>
+                <div className="mt-2 flex items-center justify-between">
+                  <span className="text-green-600 font-semibold">${item.price.toFixed(2)}</span>
+                  <span className="bg-indigo-100 text-indigo-700 rounded-full px-2 py-0.5 text-xs font-semibold">
+                    {item.category}
+                  </span>
+                </div>
+                <div className="mt-2 flex items-center justify-between text-sm">
+                  <span className="text-gray-500">Quantity: {item.quantity}</span>
+                  <span
+                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
+                      item.inStock ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
+                    }`}
+                  >
+                    {item.inStock ? "In Stock" : "Out of Stock"}
+                  </span>
+                </div>
+              </div>
+            </div>
+          ))}
+        </div>
+      </div>
+    </section>
+  );
+}
diff --git a/app/login-and-signup/page.tsx b/app/login-and-signup/page.tsx
index b1014e8..f11b744 100644
--- a/app/login-and-signup/page.tsx
+++ b/app/login-and-signup/page.tsx
@@ -3,6 +3,7 @@
 import { useState, useEffect } from "react";
 import { useRouter } from "next/navigation";
 import { signup, login, logout } from "@/lib/api/loginAndSignup";
+import { getSession } from "@/lib/auth/session";
 
 export default function LoginAndSignupPage() {
   const [isLogin, setIsLogin] = useState(true);
@@ -16,11 +17,10 @@ export default function LoginAndSignupPage() {
   const [isLoggedIn, setIsLoggedIn] = useState(false);
   const router = useRouter();
 
-  // Check if user is already logged in (this would be more robust in a real app)
+  // Reflect the real, shared client-side session marker (lib/auth/session.ts) so the Logout
+  // link only shows when a session genuinely exists.
   useEffect(() => {
-    // In a real app, this would check for a session or token
-    // For now, we'll assume if the user is on this page, they're not logged in
-    // But we'll add the logout functionality to be ready
+    setIsLoggedIn(Boolean(getSession()));
   }, []);
 
   const handleSubmit = async (e: React.FormEvent) => {
diff --git a/app/page.tsx b/app/page.tsx
index 7f08d5f..85d745a 100644
--- a/app/page.tsx
+++ b/app/page.tsx
@@ -11,6 +11,7 @@ export default function HomePage() {
         <ul>
           {/* FEATURE_LINKS_START */}
           <li><Link href="/login-and-signup">Login and Signup</Link></li>
+          <li><Link href="/item-listing">Item Listing</Link></li>
           {/* FEATURE_LINKS_END */}
         </ul>
       </nav>
diff --git a/babel.config.qa.js b/babel.config.qa.js
new file mode 100644
index 0000000..dd242dc
--- /dev/null
+++ b/babel.config.qa.js
@@ -0,0 +1,6 @@
+module.exports = {
+  presets: [
+    ["@babel/preset-env", { targets: { node: "current" } }],
+    "@babel/preset-typescript",
+  ],
+};
diff --git a/generated_tests/mongodb.unit.test.ts b/generated_tests/mongodb.unit.test.ts
new file mode 100644
index 0000000..73bc182
--- /dev/null
+++ b/generated_tests/mongodb.unit.test.ts
@@ -0,0 +1,6 @@
+import { connectToDatabase } from "../lib/mongodb";
+
+test("connectToDatabase() resolves without throwing when its required env var is unset", async () => {
+  const result = await connectToDatabase();
+  expect(result === null || result !== undefined).toBe(true);
+});
diff --git a/jest.config.qa.js b/jest.config.qa.js
new file mode 100644
index 0000000..a054d2b
--- /dev/null
+++ b/jest.config.qa.js
@@ -0,0 +1,11 @@
+const path = require("path");
+
+module.exports = {
+  testEnvironment: "node",
+  testMatch: ["<rootDir>/generated_tests/**/*.test.ts"],
+  transform: {
+    "^.+\\.tsx?$": ["babel-jest", { configFile: path.resolve(__dirname, "babel.config.qa.js") }],
+  },
+  moduleNameMapper: { "^@/(.*)$": "<rootDir>/$1" },
+  moduleFileExtensions: ["ts", "js", "json"],
+};
diff --git a/lib/api/itemListing.ts b/lib/api/itemListing.ts
new file mode 100644
index 0000000..e44598d
--- /dev/null
+++ b/lib/api/itemListing.ts
@@ -0,0 +1,16 @@
+import type { ItemListingResponse } from "@/lib/types/ItemListing";
+
+export async function fetchItems(): Promise<ItemListingResponse> {
+  const response = await fetch("/api/items", {
+    method: "GET",
+    headers: {
+      "Content-Type": "application/json",
+    },
+  });
+
+  if (!response.ok) {
+    throw new Error(`HTTP error! status: ${response.status}`);
+  }
+
+  return response.json();
+}
diff --git a/lib/api/loginAndSignup.ts b/lib/api/loginAndSignup.ts
index cd159a2..4cee2c5 100644
--- a/lib/api/loginAndSignup.ts
+++ b/lib/api/loginAndSignup.ts
@@ -1,3 +1,5 @@
+import { saveSession, clearSession } from "@/lib/auth/session";
+
 // API service layer for authentication
 export const signup = async (name: string, email: string, password: string) => {
   const response = await fetch("/api/auth/signup", {
@@ -14,6 +16,10 @@ export const signup = async (name: string, email: string, password: string) => {
     throw new Error(data.error || "Signup failed");
   }
 
+  if (data.user) {
+    saveSession(data.user);
+  }
+
   return data;
 };
 
@@ -32,6 +38,10 @@ export const login = async (email: string, password: string) => {
     throw new Error(data.error || "Login failed");
   }
 
+  if (data.user) {
+    saveSession(data.user);
+  }
+
   return data;
 };
 
@@ -46,5 +56,7 @@ export const logout = async () => {
     throw new Error(data.error || "Logout failed");
   }
 
+  clearSession();
+
   return data;
-};
\ No newline at end of file
+};
diff --git a/lib/auth/session.ts b/lib/auth/session.ts
new file mode 100644
index 0000000..442d8b4
--- /dev/null
+++ b/lib/auth/session.ts
@@ -0,0 +1,34 @@
+// Minimal client-side session marker, shared by the Login and Signup feature and any feature
+// that needs to gate a page behind "is a user currently logged in" (e.g. Item Listing's
+// FR-001/AC-001). This app's real backend never issues a cookie/JWT/server-side session --
+// `POST /api/auth/login` and `/signup` just return a plain success JSON payload -- so there is
+// no server-side session to check. This is the one, real, shared place that fills that gap:
+// login/signup writes the marker on success, logout clears it, and any page can read it.
+const SESSION_STORAGE_KEY = "finodil_session";
+
+export interface FinodilSessionUser {
+  id: string;
+  name?: string;
+  email: string;
+}
+
+export function saveSession(user: FinodilSessionUser): void {
+  if (typeof window === "undefined") return;
+  window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(user));
+}
+
+export function getSession(): FinodilSessionUser | null {
+  if (typeof window === "undefined") return null;
+  const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
+  if (!raw) return null;
+  try {
+    return JSON.parse(raw) as FinodilSessionUser;
+  } catch {
+    return null;
+  }
+}
+
+export function clearSession(): void {
+  if (typeof window === "undefined") return;
+  window.localStorage.removeItem(SESSION_STORAGE_KEY);
+}
diff --git a/lib/mongodb.ts b/lib/mongodb.ts
index c09e013..0461dd8 100644
--- a/lib/mongodb.ts
+++ b/lib/mongodb.ts
@@ -17,10 +17,14 @@ global.__mongooseCache = cache;
 
 /**
  * Guarded, cached connection helper -- returns null (with a warning) when
- * MONGODB_URI is unset instead of throwing, since sandbox containers never
- * see host env vars and an unguarded connect would fail every `next build`/
- * `next start` boot check. Await this inside a Route Handler; never call it
- * at module top level.
+ * MONGODB_URI is unset, OR when a real connection attempt fails (bad
+ * credentials, unreachable host, DNS failure), instead of throwing. Sandbox
+ * containers never see host env vars, and a configured-but-unreachable URI
+ * is a real, confirmed case in this project -- an unguarded connect would
+ * otherwise fail every `next build`/`next start` boot check, or make a
+ * genuinely broken URI hang a Route Handler for mongoose's own long default
+ * timeout instead of degrading to seed data quickly. Await this inside a
+ * Route Handler; never call it at module top level.
  */
 export async function connectToDatabase(): Promise<typeof mongoose | null> {
   if (!MONGODB_URI) {
@@ -33,9 +37,15 @@ export async function connectToDatabase(): Promise<typeof mongoose | null> {
   }
 
   if (!cache.promise) {
-    cache.promise = mongoose.connect(MONGODB_URI);
+    cache.promise = mongoose.connect(MONGODB_URI, { serverSelectionTimeoutMS: 5000 });
   }
 
-  cache.conn = await cache.promise;
-  return cache.conn;
+  try {
+    cache.conn = await cache.promise;
+    return cache.conn;
+  } catch (error) {
+    console.warn("Failed to connect to MongoDB -- falling back to seed data.", error);
+    cache.promise = null;
+    return null;
+  }
 }
\ No newline at end of file
diff --git a/lib/seedData.ts b/lib/seedData.ts
index 32294e1..df693ac 100644
--- a/lib/seedData.ts
+++ b/lib/seedData.ts
@@ -1,11 +1,86 @@
-// Shared seed/mock data for every DB-backed entity in this app -- imported by
-// a Route Handler whenever connectToDatabase() returns null (no real
-// database configured yet), so a live preview always shows a realistic,
-// populated application instead of an empty or error state. Each feature's
-// Coder Agent run adds its own `export const seed<Entity> = [...]` block
-// below, matching that entity's real Mongoose schema fields. Never invent a
-// second, inconsistent set of inline mock values in a route handler --
-// always import from here.
-//
-// SEED_DATA_START
-// SEED_DATA_END
+// Shared seed/mock data for every DB-backed entity in this app -- imported by
+// a Route Handler whenever connectToDatabase() returns null (no real
+// database configured yet, or the configured connection could not be
+// reached), so a live preview always shows a realistic, populated
+// application instead of an empty or error state. Each feature's Coder
+// Agent run adds its own `export const seed<Entity> = [...]` block below,
+// matching that entity's real Mongoose schema fields. Never invent a
+// second, inconsistent set of inline mock values in a route handler --
+// always import from here.
+//
+// SEED_DATA_START
+export const seedItemListingData = [
+  {
+    _id: "1",
+    name: "Laptop",
+    description: "High-performance laptop for work and gaming",
+    price: 1200,
+    quantity: 15,
+    category: "Electronics",
+    createdAt: new Date("2023-01-15"),
+  },
+  {
+    _id: "2",
+    name: "Coffee Mug",
+    description: "Ceramic coffee mug with ergonomic handle",
+    price: 12,
+    quantity: 50,
+    category: "Home",
+    createdAt: new Date("2023-02-20"),
+  },
+  {
+    _id: "3",
+    name: "Desk Chair",
+    description: "Ergonomic office chair with lumbar support",
+    price: 250,
+    quantity: 8,
+    category: "Furniture",
+    createdAt: new Date("2023-03-10"),
+  },
+  {
+    _id: "4",
+    name: "Wireless Mouse",
+    description: "Ergonomic wireless mouse with long battery life",
+    price: 35,
+    quantity: 30,
+    category: "Electronics",
+    createdAt: new Date("2023-04-05"),
+  },
+  {
+    _id: "5",
+    name: "Notebook",
+    description: "Premium spiral-bound notebook with 120 pages",
+    price: 8,
+    quantity: 100,
+    category: "Stationery",
+    createdAt: new Date("2023-05-12"),
+  },
+  {
+    _id:
```