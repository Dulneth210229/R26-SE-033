"""
Workspace / Git service.

Each project gets exactly one persistent Git repository on disk:

    workspaces/{project_slug}/repo/

This is the real, growing Next.js (App Router + TypeScript) codebase the
Coder Agent will edit feature by feature. Git already gives us branching,
diffing, and rollback for source code specifically, so we use it directly
instead of reinventing version tracking on top of the artifact versioning
system used for documents/diagrams.

Every feature is developed on its own branch (feature/{feature_slug}) and only
merged into main after human approval.

Stack history: this project originally generated a MERN (Express `server/` +
Vite/React `client/`) scaffold. It was migrated to Next.js (see CLAUDE.md,
"MERN -> Next.js migration") -- new projects now get the Next.js scaffold
below. Two real, already-existing projects predate the migration and are
genuinely MERN; `_detect_stack` recognizes an existing MERN repo by its
`server/src/app.js` and leaves it completely frozen on the legacy scaffold
(see the MERN_* constants and `_backfill_mern_scaffold*` methods below) rather
than attempting an in-place migration -- there is no code path that writes
Next.js files into a repo already on the MERN convention, or vice versa.
"""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from git import GitCommandError, Repo

from app.core.config import settings
from app.services.in_memory_store import store
from app.utils.logger import get_logger
from app.utils.slugify import slugify

logger = get_logger(__name__)

MAIN_BRANCH = "main"

# ---------------------------------------------------------------------------
# Next.js (App Router + TypeScript) scaffold -- the current default for every
# newly-created project.
#
# Next/React/TypeScript versions are pinned to an EXACT release (no `^`/
# `latest`) rather than a range: the `params`/`searchParams` contract on page
# components and Route Handlers is a plain object in Next 14 and a Promise
# requiring `await` in Next 15+ -- a breaking change the Coder Agent's own
# prompt is written against one specific contract for. Next 14 (the
# synchronous contract) was chosen deliberately as the simpler of the two for
# a local, occasionally-unreliable model to get right.
# ---------------------------------------------------------------------------

NEXTJS_GITIGNORE = """\
node_modules/
.next/
.env
.env*.local
*.tsbuildinfo
next-env.d.ts
"""

NEXTJS_PACKAGE_JSON = """\
{
  "name": "auto-forge-generated-app",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "next": "14.2.5",
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "mongoose": "8.5.0"
  },
  "devDependencies": {
    "typescript": "5.5.4",
    "@types/node": "20.14.15",
    "@types/react": "18.3.3",
    "@types/react-dom": "18.3.0",
    "eslint": "8.57.0",
    "eslint-config-next": "14.2.5",
    "tailwindcss": "3.4.7",
    "postcss": "8.4.40",
    "autoprefixer": "10.4.19"
  }
}
"""

# Content-based globs, not just app/components -- covers every directory a
# feature might reasonably add className usage to, matching the convention
# most Next.js/Tailwind starters ship with.
NEXTJS_TAILWIND_CONFIG = """\
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
"""

# `.mjs` specifically, not `.js` -- this project's own history already hit a
# real build failure once from a CommonJS postcss.config.js colliding with
# package.json's Next.js-implied module resolution (see the workspace
# scaffold gotchas in CLAUDE.md); `.mjs` forces ESM regardless of
# package.json's own "type" field, the same lesson next.config.mjs already
# encodes for this project's config files.
NEXTJS_POSTCSS_CONFIG = """\
/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};

export default config;
"""

NEXTJS_ESLINTRC_JSON = """\
{
  "extends": "next/core-web-vitals"
}
"""

NEXTJS_TSCONFIG_JSON = """\
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
"""

# Next.js 14 (pinned above) does NOT support next.config.ts -- TypeScript
# config file support was only added in Next.js 15. Using next.config.mjs
# (plain JS, ESM via the .mjs extension regardless of package.json's own
# "type" field) is the correct convention for this pinned version -- a real,
# confirmed build failure otherwise ("Configuring Next.js via
# 'next.config.ts' is not supported. Please replace the file with
# 'next.config.js' or 'next.config.mjs'.").
NEXTJS_NEXT_CONFIG = """\
/** @type {import('next').NextConfig} */
const nextConfig = {};

export default nextConfig;
"""

NEXTJS_APP_LAYOUT = """\
import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import PreviewRouteAnnouncer from "@/components/PreviewRouteAnnouncer";

export const metadata: Metadata = {
  title: "Auto-Forge Generated App",
  description: "Generated by Auto-Forge MAS",
};

export const viewport = "width=device-width, initial-scale=1";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <PreviewRouteAnnouncer />
        <header className="border-b border-gray-200 bg-white px-6 py-4">
          <Link href="/" className="font-semibold text-gray-900">
            Auto-Forge Generated App
          </Link>
        </header>
        <main>{children}</main>
        <footer className="border-t border-gray-200 bg-white px-6 py-4 text-sm text-gray-500">
          © {new Date().getFullYear()} Auto-Forge Generated App
        </footer>
      </body>
    </html>
  );
}
"""

# Announces the current route to a parent window (the AutoForge frontend's Live Preview panel,
# when this app happens to be running inside its preview iframe) via postMessage -- the iframe's
# origin is always different from the frontend's own origin (a dynamically Docker-assigned host
# port), so the parent cannot read iframe.contentWindow.location directly; postMessage is the
# only mechanism that works across that boundary. "*" targetOrigin is deliberate here: the
# payload is just a pathname (never sensitive), and this app only ever runs on the human's own
# machine -- the parent-side listener is what actually enforces an origin check on receipt (see
# PreviewPanel.jsx). Harmless when NOT running inside a preview iframe (window.parent === window
# in that case, so this just messages the app's own window with nothing listening).
NEXTJS_PREVIEW_ROUTE_ANNOUNCER = """\
"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

export default function PreviewRouteAnnouncer() {
  const pathname = usePathname();

  useEffect(() => {
    window.parent.postMessage({ type: "autoforge-preview-route", path: pathname }, "*");
  }, [pathname]);

  return null;
}
"""

NEXTJS_APP_PAGE = """\
export default function HomePage() {
  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Auto-Forge Generated App</h1>
      <p>Feature pages are registered as links below.</p>
      <nav>
        <ul>
          {/* FEATURE_LINKS_START */}
          {/* FEATURE_LINKS_END */}
        </ul>
      </nav>
    </div>
  );
}
"""

# Frozen, exact content of NEXTJS_APP_PAGE at scaffold introduction -- kept as
# a placeholder for a future fingerprint-based upgrade path, mirroring the
# MERN scaffold's own _LEGACY_*_V1 precedent, should app/page.tsx ever need a
# backward-compatible upgrade the way CLIENT_APP_JSX did. Not used yet: the
# Next.js scaffold has had no upgrades since its introduction.
_LEGACY_NEXTJS_APP_PAGE_V1 = NEXTJS_APP_PAGE

NEXTJS_APP_GLOBALS_CSS = """\
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
"""

NEXTJS_HEALTH_ROUTE = """\
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ status: "ok" });
}
"""

NEXTJS_LIB_MONGODB = """\
import mongoose from "mongoose";

const MONGODB_URI = process.env.MONGODB_URI;

type MongooseCache = {
  conn: typeof mongoose | null;
  promise: Promise<typeof mongoose> | null;
};

declare global {
  // eslint-disable-next-line no-var
  var __mongooseCache: MongooseCache | undefined;
}

const cache: MongooseCache = global.__mongooseCache ?? { conn: null, promise: null };
global.__mongooseCache = cache;

/**
 * Guarded, cached connection helper -- returns null (with a warning) when
 * MONGODB_URI is unset instead of throwing, since sandbox containers never
 * see host env vars and an unguarded connect would fail every `next build`/
 * `next start` boot check. Await this inside a Route Handler; never call it
 * at module top level.
 */
export async function connectToDatabase(): Promise<typeof mongoose | null> {
  if (!MONGODB_URI) {
    console.warn("MONGODB_URI is not set -- skipping database connection.");
    return null;
  }

  if (cache.conn) {
    return cache.conn;
  }

  if (!cache.promise) {
    cache.promise = mongoose.connect(MONGODB_URI);
  }

  cache.conn = await cache.promise;
  return cache.conn;
}
"""

NEXTJS_ENV_EXAMPLE = """\
MONGODB_URI=mongodb://localhost:27017/auto-forge-generated-app
"""

NEXTJS_SEED_DATA = """\
// Shared seed/mock data for every DB-backed entity in this app -- imported by
// a Route Handler whenever connectToDatabase() returns null (no real
// database configured yet), so a live preview always shows a realistic,
// populated application instead of an empty or error state. Each feature's
// Coder Agent run adds its own `export const seed<Entity> = [...]` block
// below, matching that entity's real Mongoose schema fields. Never invent a
// second, inconsistent set of inline mock values in a route handler --
// always import from here.
//
// SEED_DATA_START
// SEED_DATA_END
"""

# path (relative to repo root) -> content. Anything already on disk is left
# untouched -- this is a backfill for what's missing, never an overwrite of
# whatever a feature branch/coding loop has since added on top.
NEXTJS_SCAFFOLD_FILES: dict[str, str] = {
    "package.json": NEXTJS_PACKAGE_JSON,
    ".eslintrc.json": NEXTJS_ESLINTRC_JSON,
    "tsconfig.json": NEXTJS_TSCONFIG_JSON,
    "next.config.mjs": NEXTJS_NEXT_CONFIG,
    "tailwind.config.js": NEXTJS_TAILWIND_CONFIG,
    "postcss.config.mjs": NEXTJS_POSTCSS_CONFIG,
    "app/layout.tsx": NEXTJS_APP_LAYOUT,
    "components/PreviewRouteAnnouncer.tsx": NEXTJS_PREVIEW_ROUTE_ANNOUNCER,
    "app/page.tsx": NEXTJS_APP_PAGE,
    "app/globals.css": NEXTJS_APP_GLOBALS_CSS,
    "app/api/health/route.ts": NEXTJS_HEALTH_ROUTE,
    "lib/mongodb.ts": NEXTJS_LIB_MONGODB,
    "lib/seedData.ts": NEXTJS_SEED_DATA,
    ".env.example": NEXTJS_ENV_EXAMPLE,
}


# ---------------------------------------------------------------------------
# Legacy MERN (Express `server/` + Vite/React `client/`) scaffold -- kept,
# unchanged in content, so the two real pre-migration projects
# (e-commerce-platform, taskflow) stay reproducible and frozen on their
# original convention. Never written into a repo `_detect_stack` identifies
# as Next.js, and never mixed with the Next.js scaffold above.
# ---------------------------------------------------------------------------

MERN_GITIGNORE = """\
node_modules/
.env
dist/
build/
*.log
"""

MERN_ROOT_PACKAGE_JSON = """\
{
  "name": "auto-forge-generated-app",
  "private": true,
  "scripts": {
    "install:all": "npm install --prefix server && npm install --prefix client",
    "dev": "concurrently \\"npm run dev --prefix server\\" \\"npm run dev --prefix client\\"",
    "build": "npm run build --prefix client"
  },
  "devDependencies": {
    "concurrently": "^8.2.2"
  }
}
"""

MERN_SERVER_PACKAGE_JSON = """\
{
  "name": "auto-forge-server",
  "private": true,
  "type": "commonjs",
  "scripts": {
    "start": "node src/server.js",
    "dev": "nodemon src/server.js"
  },
  "dependencies": {
    "express": "^4.19.2",
    "cors": "^2.8.5",
    "dotenv": "^16.4.5",
    "mongoose": "^8.5.0",
    "helmet": "^7.1.0",
    "express-rate-limit": "^7.4.0"
  },
  "devDependencies": {
    "nodemon": "^3.1.4"
  }
}
"""

MERN_SERVER_APP_JS = """\
const express = require("express");
const cors = require("cors");
const helmet = require("helmet");
const rateLimit = require("express-rate-limit");

const app = express();

app.use(helmet());
app.use(cors());
app.use(express.json());

const apiLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100,
  standardHeaders: true,
  legacyHeaders: false,
});
app.use("/api/", apiLimiter);

app.get("/api/health", (req, res) => {
  res.json({ status: "ok" });
});

// FEATURE_ROUTES_START
// FEATURE_ROUTES_END

app.use((err, req, res, next) => {
  console.error(err.stack);
  const status = err.status || 500;
  res.status(status).json({ error: { message: err.message || "Internal Server Error" } });
});

module.exports = app;
"""

MERN_SERVER_SERVER_JS = """\
require("dotenv").config();
const mongoose = require("mongoose");
const app = require("./app");

const PORT = process.env.PORT || 5000;
const MONGODB_URI = process.env.MONGODB_URI;

async function start() {
  if (MONGODB_URI) {
    try {
      await mongoose.connect(MONGODB_URI);
      console.log("Connected to MongoDB");
    } catch (error) {
      console.error("Failed to connect to MongoDB:", error.message);
    }
  } else {
    console.warn("MONGODB_URI is not set -- starting without a database connection.");
  }

  app.listen(PORT, () => {
    console.log(`Server listening on port ${PORT}`);
  });
}

start();
"""

# Frozen, exact content of MERN_SERVER_APP_JS/MERN_SERVER_SERVER_JS before the
# helmet/rate-limit/mongoose.connect/error-handler upgrade above -- used by
# _upgrade_server_app_js/_upgrade_server_server_js to detect a file that is
# provably still the untouched original scaffold (safe to replace wholesale)
# versus one a feature has since customized (needs targeted insertion
# instead). Never change these two constants after the fact.
_LEGACY_SERVER_APP_JS_V1 = """\
const express = require("express");
const cors = require("cors");

const app = express();

app.use(cors());
app.use(express.json());

app.get("/api/health", (req, res) => {
  res.json({ status: "ok" });
});

module.exports = app;
"""

_LEGACY_SERVER_SERVER_JS_V1 = """\
require("dotenv").config();
const app = require("./app");

const PORT = process.env.PORT || 5000;

app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});
"""

MERN_SERVER_ENV_EXAMPLE = """\
PORT=5000
MONGODB_URI=mongodb://localhost:27017/auto-forge-generated-app
JWT_SECRET=change-me
"""

MERN_CLIENT_PACKAGE_JSON = """\
{
  "name": "auto-forge-client",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.0"
  }
}
"""

MERN_CLIENT_VITE_CONFIG = """\
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
"""

MERN_CLIENT_INDEX_HTML = """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Auto-Forge Generated App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""

MERN_CLIENT_MAIN_JSX = """\
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
"""

MERN_CLIENT_APP_JSX = """\
import React from "react";
import { Routes, Route, Link } from "react-router-dom";

function HomePage() {
  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Auto-Forge Generated App</h1>
      <p>Feature pages are registered as routes below.</p>
      <nav>
        <ul>
          {/* FEATURE_LINKS_START */}
          {/* FEATURE_LINKS_END */}
        </ul>
      </nav>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
    </Routes>
  );
}
"""

# Frozen, exact content of MERN_CLIENT_APP_JSX before the FEATURE_LINKS marker
# upgrade above -- used by _upgrade_client_app_jsx to detect a file that is
# provably still the untouched original scaffold (safe to replace wholesale)
# versus one a feature has since customized (needs targeted insertion instead).
# Never change this constant after the fact.
_LEGACY_CLIENT_APP_JSX_V1 = """\
import React from "react";
import { Routes, Route } from "react-router-dom";

function HomePage() {
  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Auto-Forge Generated App</h1>
      <p>Feature pages are registered as routes below.</p>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
    </Routes>
  );
}
"""

MERN_CLIENT_INDEX_CSS = """\
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
"""

# path (relative to repo root) -> content, for the legacy MERN scaffold only.
MERN_SCAFFOLD_FILES: dict[str, str] = {
    "server/package.json": MERN_SERVER_PACKAGE_JSON,
    "server/src/app.js": MERN_SERVER_APP_JS,
    "server/src/server.js": MERN_SERVER_SERVER_JS,
    "server/.env.example": MERN_SERVER_ENV_EXAMPLE,
    "client/package.json": MERN_CLIENT_PACKAGE_JSON,
    "client/vite.config.js": MERN_CLIENT_VITE_CONFIG,
    "client/index.html": MERN_CLIENT_INDEX_HTML,
    "client/src/main.jsx": MERN_CLIENT_MAIN_JSX,
    "client/src/App.jsx": MERN_CLIENT_APP_JSX,
    "client/src/index.css": MERN_CLIENT_INDEX_CSS,
}


class WorkspaceService:
    """
    Manages one persistent Git repository per project.
    """

    def _project_slug(self, project_id: str) -> str:
        project = store.projects.get(project_id)

        if not project:
            raise ValueError(f"Project not found: {project_id}")

        return slugify(project.get("project_name") or project_id)

    def _feature_slug(self, feature_id: str) -> str:
        feature = store.features.get(feature_id)

        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")

        return slugify(feature.get("feature_name") or feature_id)

    def _repo_path(self, project_id: str) -> Path:
        return Path(settings.WORKSPACE_DIR) / self._project_slug(project_id) / "repo"

    def get_repo_path(self, project_id: str) -> Path:
        """
        Return the on-disk path of the project's repo (used by SandboxService to
        bind-mount the workspace). Does not require the repo to exist yet.
        """
        return self._repo_path(project_id)

    def write_env_local(self, project_id: str, values: dict[str, str]) -> bool:
        """
        Merge `values` into `.env.local` at the workspace root, creating the
        file if absent and preserving any key not present in `values`.

        This is the only realistic way a human-provided value (e.g. a real
        MongoDB URI) can ever reach a generated app's runtime: sandbox/preview
        containers never see host env vars, and Docker has no mechanism to
        inject an env var into an already-running container -- so this must
        be a file the container picks up on its NEXT start (preview_service's
        stop+restart, or the next `next build`/`next start` inside verify()).

        A plain filesystem operation, not a git one -- `.env.local` is always
        gitignored by the scaffold (see NEXTJS_GITIGNORE), so writing here
        never needs to worry about which branch is currently checked out
        (untracked files survive a `git checkout` unaffected). Calls
        ensure_project_repo() first so this also works before any Coder Agent
        run has ever created the workspace (e.g. a URI arriving on the very
        first message to a brand-new feature).

        Returns True iff something on disk actually changed.
        """
        self.ensure_project_repo(project_id)
        repo_path = self._repo_path(project_id)
        env_path = repo_path / ".env.local"

        existing = self.read_env_local(project_id)

        if env_path.exists() and all(existing.get(key) == value for key, value in values.items()):
            return False

        merged = {**existing, **values}
        env_path.write_text(
            "\n".join(f"{key}={value}" for key, value in merged.items()) + "\n", encoding="utf-8"
        )
        return True

    def read_env_local(self, project_id: str) -> dict[str, str]:
        """Read `.env.local` at the workspace root, if present. Returns {} if absent."""
        env_path = self._repo_path(project_id) / ".env.local"
        if not env_path.exists():
            return {}

        values: dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
        return values

    def remove_env_local_keys(self, project_id: str, keys: list[str]) -> bool:
        """
        Remove `keys` from `.env.local` at the workspace root, if present -- the removal
        counterpart to write_env_local (which only ever merges values in; there was no way to
        take one back out). Same contract: a no-op (returns False) if the file doesn't exist or
        none of `keys` are currently present; otherwise rewrites the file with those keys gone
        and every other key preserved untouched. Does not delete the file itself even if it ends
        up empty -- a project may still want an empty `.env.local` present for a future write.
        """
        self.ensure_project_repo(project_id)
        env_path = self._repo_path(project_id) / ".env.local"

        if not env_path.exists():
            return False

        existing = self.read_env_local(project_id)
        remaining = {key: value for key, value in existing.items() if key not in keys}

        if remaining == existing:
            return False

        env_path.write_text(
            "\n".join(f"{key}={value}" for key, value in remaining.items()) + ("\n" if remaining else ""),
            encoding="utf-8",
        )
        return True

    def _feature_branch_name(self, feature_id: str) -> str:
        return f"feature/{self._feature_slug(feature_id)}"

    def _detect_stack(self, repo_path: Path) -> str:
        """
        Identify which generated-app convention this repo's working tree
        already follows, so ensure_project_repo backfills the RIGHT scaffold
        instead of writing a Next.js tree alongside an existing MERN one (or
        vice versa). Two pre-existing real projects (e-commerce-platform,
        taskflow) are genuinely MERN and must stay frozen on that convention
        forever, never partially migrated.

        Returns "nextjs" or "mern". A repo with neither marker present (e.g.
        a fresh git init with nothing committed yet) is treated as "nextjs",
        since that's the current default going forward.
        """
        if (repo_path / "server" / "src" / "app.js").exists():
            return "mern"

        return "nextjs"

    def ensure_project_repo(self, project_id: str) -> Repo:
        """
        Return the project's Git repo, initializing and scaffolding it on
        first use with the current default (Next.js App Router +
        TypeScript). Also backfills any missing scaffold files into an
        already-existing repo, using whichever convention (_detect_stack)
        that repo is already on -- a legacy MERN repo only ever gets MERN
        backfills (see _backfill_mern_scaffold/_backfill_mern_scaffold_
        upgrades), never Next.js files, and vice versa.
        """
        repo_path = self._repo_path(project_id)

        if (repo_path / ".git").exists():
            repo = Repo(repo_path)
            stack = self._detect_stack(repo_path)

            if stack == "mern":
                self._backfill_mern_scaffold(repo, repo_path)
                self._backfill_mern_scaffold_upgrades(repo, repo_path)
            else:
                self._backfill_nextjs_scaffold(repo, repo_path)
                self._backfill_nextjs_scaffold_upgrades(repo, repo_path)

            return repo

        repo_path.mkdir(parents=True, exist_ok=True)
        repo = Repo.init(repo_path, initial_branch=MAIN_BRANCH)

        (repo_path / ".gitignore").write_text(NEXTJS_GITIGNORE, encoding="utf-8")

        for relative_path, content in NEXTJS_SCAFFOLD_FILES.items():
            file_path = repo_path / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        repo.index.add([".gitignore", *NEXTJS_SCAFFOLD_FILES.keys()])
        repo.index.commit("Initial project scaffold: Next.js App Router + TypeScript + MongoDB")

        return repo

    def _backfill_nextjs_scaffold(self, repo: Repo, repo_path: Path) -> None:
        """
        Add any Next.js scaffold file that's missing from the currently
        checked-out branch's working tree, without touching anything already
        there -- the Next.js-scaffold counterpart of _backfill_mern_scaffold,
        for a repo _detect_stack has already identified as "nextjs".

        Deliberately does NOT force a checkout to main first: it commits onto
        whatever branch is currently active, matching the MERN backfill's own
        established rationale (see _backfill_mern_scaffold).

        Also removes a stale `next.config.ts` left over from before the
        Next.js scaffold's config file was renamed to `next.config.mjs`
        (Next.js 14, which this project is pinned to, does not support
        `next.config.ts` at all -- TypeScript config file support was only
        added in Next.js 15 -- and its mere PRESENCE breaks `next build`
        with a hard error regardless of `next.config.mjs` also existing;
        confirmed directly against a real pre-rename repo). A brand-new
        project never has this file, so this is a one-time cleanup for a
        repo scaffolded before that rename, not something every backfill
        call needs to worry about going forward.
        """
        stale_ts_config = repo_path / "next.config.ts"
        removed_stale_config = stale_ts_config.exists()
        if removed_stale_config:
            stale_ts_config.unlink()

        missing = {
            relative_path: content
            for relative_path, content in NEXTJS_SCAFFOLD_FILES.items()
            if not (repo_path / relative_path).exists()
        }

        if not missing and not removed_stale_config:
            return

        for relative_path, content in missing.items():
            file_path = repo_path / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        gitignore_path = repo_path / ".gitignore"
        changed_paths = list(missing.keys())
        if not gitignore_path.exists():
            gitignore_path.write_text(NEXTJS_GITIGNORE, encoding="utf-8")
            changed_paths.append(".gitignore")

        if changed_paths:
            repo.index.add(changed_paths)
        if removed_stale_config:
            try:
                repo.index.remove(["next.config.ts"])
            except Exception:
                pass  # not tracked (e.g. an untracked stray file) -- nothing to stage

        repo.index.commit("Backfill missing Next.js scaffold files")

    def _backfill_nextjs_scaffold_upgrades(self, repo: Repo, repo_path: Path) -> None:
        """
        Upgrade an already-scaffolded Next.js repo with scaffold changes
        introduced after that repo was first created:
        - Tailwind CSS, which the original Next.js scaffold shipped without
          -- every generated page's Tailwind utility classNames were inert,
          unprocessed class-name soup with zero visual effect until this
          upgrade lands.
        - PreviewRouteAnnouncer, which the original app/layout.tsx never
          mounted -- without it, the frontend's Live Preview panel can never
          learn which route the human is actually looking at inside the
          preview iframe (a genuinely cross-origin iframe -- the parent
          cannot read iframe.contentWindow.location directly), so the
          displayed URL never updates past the initial base URL.

        `tailwind.config.js`/`postcss.config.mjs`/`components/
        PreviewRouteAnnouncer.tsx` are all handled by _backfill_nextjs_
        scaffold's own missing-file check (NEXTJS_SCAFFOLD_FILES already
        lists them) -- this method only handles EXISTING files a fresh
        backfill can't touch without clobbering feature-specific
        customization: package.json (merge, never overwrite -- see
        _merge_package_json), globals.css (append the three @tailwind
        directives only if not already present), and app/layout.tsx (insert
        the announcer's import + mount only if not already present, via a
        stable marker check + anchored insertion -- never a wholesale
        replace, since unlike globals.css, layout.tsx is a real, plausible
        target for a feature's own future customization, e.g. an added
        provider).
        """
        changed_paths: list[str] = []
        upgrade_descriptions: list[str] = []

        package_json_path = repo_path / "package.json"
        if package_json_path.exists() and self._merge_package_json(
            package_json_path,
            dev_dependencies={
                "tailwindcss": "3.4.7",
                "postcss": "8.4.40",
                "autoprefixer": "10.4.19",
            },
        ):
            changed_paths.append("package.json")
            upgrade_descriptions.append("Tailwind CSS")

        globals_css_path = repo_path / "app" / "globals.css"
        if globals_css_path.exists() and self._upgrade_globals_css_for_tailwind(globals_css_path):
            changed_paths.append("app/globals.css")
            if "Tailwind CSS" not in upgrade_descriptions:
                upgrade_descriptions.append("Tailwind CSS")

        layout_path = repo_path / "app" / "layout.tsx"
        if layout_path.exists() and self._upgrade_layout_for_preview_route_announcer(layout_path):
            changed_paths.append("app/layout.tsx")
            upgrade_descriptions.append("live preview route tracking")

        if layout_path.exists() and self._upgrade_layout_for_persistent_nav_footer(layout_path):
            if "app/layout.tsx" not in changed_paths:
                changed_paths.append("app/layout.tsx")
            upgrade_descriptions.append("persistent nav/footer")

        if not changed_paths:
            return

        repo.index.add(changed_paths)
        repo.index.commit(f"Backfill scaffold upgrades: {', '.join(upgrade_descriptions)}")

    def _upgrade_globals_css_for_tailwind(self, globals_css_path: Path) -> bool:
        """
        Prepend the three @tailwind directives to an existing globals.css
        that predates this scaffold upgrade, leaving every other line (any
        feature-added custom CSS) exactly where it is. A no-op, returning
        False, if the directives are already present.
        """
        content = globals_css_path.read_text(encoding="utf-8")
        if "@tailwind" in content:
            return False

        globals_css_path.write_text(
            "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\n" + content,
            encoding="utf-8",
        )
        return True

    def _upgrade_layout_for_preview_route_announcer(self, layout_path: Path) -> bool:
        """
        Insert PreviewRouteAnnouncer's import + mount into an existing app/layout.tsx that
        predates this feature, without touching anything else a feature may have already added
        to the layout (a provider, extra metadata, etc.).

        Requires BOTH anchors (the globals.css import line, and the literal
        `<body>{children}</body>` line) to be present and does nothing at all if either is
        missing -- deliberately strict, since inserting the mount without its matching import
        (or vice versa) would produce a real build error rather than a silently-incomplete
        upgrade. No-ops (with a logged warning) rather than corrupting the file.
        """
        content = layout_path.read_text(encoding="utf-8")
        if "PreviewRouteAnnouncer" in content:
            return False

        import_anchor = 'import "./globals.css";'
        body_anchor = "<body>{children}</body>"
        if import_anchor not in content or body_anchor not in content:
            logger.warning(
                "Could not backfill PreviewRouteAnnouncer into %s -- expected anchor(s) not "
                "found (the file has likely already been customized past recognition). "
                "Skipping.",
                layout_path,
            )
            return False

        updated = content.replace(
            import_anchor,
            f'{import_anchor}\nimport PreviewRouteAnnouncer from "@/components/PreviewRouteAnnouncer";',
            1,
        )
        updated = updated.replace(
            body_anchor,
            "<body>\n        <PreviewRouteAnnouncer />\n        {children}\n      </body>",
            1,
        )
        layout_path.write_text(updated, encoding="utf-8")
        return True

    def _upgrade_layout_for_persistent_nav_footer(self, layout_path: Path) -> bool:
        """
        Insert a minimal, deterministic persistent header (app name, linking back to `/`) and
        footer around {children} into an existing app/layout.tsx that predates this upgrade --
        without this, only the Home page has its own local nav (FEATURE_LINKS), so any OTHER
        route renders with zero nav/footer at all (a real, reported bug).

        Anchors on the literal `<PreviewRouteAnnouncer />\\n        {children}\\n      </body>`
        block -- this function is wired to run strictly AFTER
        _upgrade_layout_for_preview_route_announcer in _backfill_nextjs_scaffold_upgrades, and a
        fresh scaffold's own NEXTJS_APP_LAYOUT template is seeded with the identical text, so the
        anchor is present either way by the time this runs. No-ops (with a logged warning) if the
        anchor is missing (customized past recognition) or a `<header` tag already exists
        (nav/footer already added -- checking for the literal `<header` tag rather than the
        "Auto-Forge Generated App" text, since that text also appears, unrelatedly, inside every
        layout's own `metadata.title`).
        """
        content = layout_path.read_text(encoding="utf-8")
        if "<header" in content:
            return False

        body_anchor = "<PreviewRouteAnnouncer />\n        {children}\n      </body>"
        if body_anchor not in content:
            logger.warning(
                "Could not backfill a persistent nav/footer into %s -- expected anchor not "
                "found (the file has likely already been customized past recognition, or "
                "predates PreviewRouteAnnouncer itself and needs that upgrade first). Skipping.",
                layout_path,
            )
            return False

        updated = content
        if 'import Link from "next/link";' not in updated:
            globals_css_import = 'import "./globals.css";'
            if globals_css_import in updated:
                updated = updated.replace(
                    globals_css_import,
                    f'import Link from "next/link";\n{globals_css_import}',
                    1,
                )

        updated = updated.replace(
            body_anchor,
            "<PreviewRouteAnnouncer />\n"
            '        <header className="border-b border-gray-200 bg-white px-6 py-4">\n'
            '          <Link href="/" className="font-semibold text-gray-900">\n'
            "            Auto-Forge Generated App\n"
            "          </Link>\n"
            "        </header>\n"
            "        <main>{children}</main>\n"
            '        <footer className="border-t border-gray-200 bg-white px-6 py-4 text-sm '
            'text-gray-500">\n'
            "          © {new Date().getFullYear()} Auto-Forge Generated App\n"
            "        </footer>\n"
            "      </body>",
            1,
        )
        layout_path.write_text(updated, encoding="utf-8")
        return True

    def _backfill_mern_scaffold(self, repo: Repo, repo_path: Path) -> None:
        """
        Add any legacy MERN scaffold file that's missing from the currently
        checked-out branch's working tree, without touching anything already
        there.

        This exists because a project's repo may have been created before
        this scaffold was introduced (or before a given scaffold file was
        added to it) -- without this, an old repo is permanently stuck with
        whatever bare-bones state ensure_project_repo used to create, since
        that method previously only ran its scaffolding logic once, at
        Repo.init time.

        Deliberately does NOT force a checkout to main first: it commits onto
        whatever branch is currently active. Called from start_feature_branch
        before that method's own checkout(MAIN_BRANCH), so the common case
        (repo idle on main between features) backfills main directly; called
        mid-coding-loop (build_coder_tools) it backfills the feature branch,
        which then carries the fix into main on the next merge either way.
        """
        missing = {
            relative_path: content
            for relative_path, content in MERN_SCAFFOLD_FILES.items()
            if not (repo_path / relative_path).exists()
        }

        changed_paths = list(missing.keys())

        for relative_path, content in missing.items():
            file_path = repo_path / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        if self._backfill_mern_root_package_json(repo_path):
            changed_paths.append("package.json")

        if not changed_paths:
            return

        repo.index.add(changed_paths)
        repo.index.commit("Backfill missing runnable-scaffold files")

    def _backfill_mern_root_package_json(self, repo_path: Path) -> bool:
        """
        Merge the root install:all/dev/build scripts and the concurrently
        devDependency into an existing root package.json, without touching
        any dependencies a pre-scaffold project may have declared there.

        This is separate from MERN_SCAFFOLD_FILES because the root
        package.json isn't a create-if-missing file -- ensure_project_repo
        guarantees it always exists, so the only thing that can be missing
        here is its scripts (e.g. a repo created before this scaffold
        existed at all).
        """
        return self._merge_package_json(
            repo_path / "package.json",
            scripts={
                "install:all": "npm install --prefix server && npm install --prefix client",
                "dev": 'concurrently "npm run dev --prefix server" "npm run dev --prefix client"',
                "build": "npm run build --prefix client",
            },
            dev_dependencies={"concurrently": "^8.2.2"},
        )

    def _merge_package_json(
        self,
        package_json_path: Path,
        scripts: dict[str, str] | None = None,
        dependencies: dict[str, str] | None = None,
        dev_dependencies: dict[str, str] | None = None,
    ) -> bool:
        """
        Add any of the given scripts/dependencies/devDependencies that are
        missing from an existing package.json, leaving everything else
        (including any already-present entry with the same key) untouched.
        Returns True if the file was changed.

        Purely additive, never destructive -- safe to call on a file that a
        feature has already customized, unlike the fingerprint-based
        wholesale-replace path used for app.js/server.js (a dependency list
        has no equivalent notion of "this line must come before that line,"
        so a plain dict merge is always safe here). Stack-agnostic -- usable
        for either the MERN or Next.js scaffold's package.json.
        """
        try:
            data = json.loads(package_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        changed = False

        for section, entries in [
            ("scripts", scripts),
            ("dependencies", dependencies),
            ("devDependencies", dev_dependencies),
        ]:
            if not entries:
                continue

            existing = data.setdefault(section, {})
            for name, value in entries.items():
                if name not in existing:
                    existing[name] = value
                    changed = True

        if not changed:
            return False

        package_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return True

    def _backfill_mern_scaffold_upgrades(self, repo: Repo, repo_path: Path) -> None:
        """
        Upgrade an already-scaffolded legacy MERN repo with security/DB/
        error-handling middleware added to the scaffold template after that
        repo was first created, without clobbering feature-specific
        customization already layered on top (e.g. a real feature's router
        mounted into app.js).

        Unlike _backfill_mern_scaffold (pure file-existence check), the
        files touched here already exist in any repo scaffolded before this
        upgrade shipped, so "missing" never fires. Uses content
        fingerprinting instead: a file that still matches its own frozen
        legacy template exactly is provably untouched and gets replaced
        wholesale; anything else is assumed customized and gets targeted,
        anchor-based insertions instead (see _upgrade_server_app_js).
        """
        changed_paths: list[str] = []

        app_js_path = repo_path / "server" / "src" / "app.js"
        if app_js_path.exists() and self._upgrade_server_app_js(app_js_path):
            changed_paths.append("server/src/app.js")

        server_js_path = repo_path / "server" / "src" / "server.js"
        if server_js_path.exists() and self._upgrade_server_server_js(server_js_path):
            changed_paths.append("server/src/server.js")

        server_package_json_path = repo_path / "server" / "package.json"
        if server_package_json_path.exists() and self._merge_package_json(
            server_package_json_path,
            dependencies={"helmet": "^7.1.0", "express-rate-limit": "^7.4.0"},
        ):
            changed_paths.append("server/package.json")

        app_jsx_path = repo_path / "client" / "src" / "App.jsx"
        if app_jsx_path.exists() and self._upgrade_client_app_jsx(app_jsx_path):
            changed_paths.append("client/src/App.jsx")

        if not changed_paths:
            return

        repo.index.add(changed_paths)
        repo.index.commit(
            "Backfill scaffold upgrades: security middleware, DB connection, error handling, "
            "home page navigation"
        )

    def _upgrade_server_app_js(self, path: Path) -> bool:
        """
        Add helmet, rate limiting, a FEATURE_ROUTES marker pair, and a
        catch-all error handler to an existing server/src/app.js.

        Wholesale-replaces the file only if it's provably still the exact,
        untouched original scaffold. Otherwise anchors targeted insertions
        on `const app = express();` (guaranteed present -- nothing in this
        file works without it) and `module.exports = app;` (guaranteed
        present -- server.js's require("./app") depends on it), which stay
        valid regardless of whatever a feature has already added in
        between (e.g. a mounted router).
        """
        content = path.read_text(encoding="utf-8")

        if content == _LEGACY_SERVER_APP_JS_V1:
            path.write_text(MERN_SERVER_APP_JS, encoding="utf-8")
            return True

        if "const app = express();" not in content or "module.exports = app;" not in content:
            logger.warning(
                "server/src/app.js has diverged too far from the scaffold template to "
                "safely auto-upgrade (missing a required anchor line) -- skipping."
            )
            return False

        updated = content

        if "helmet" not in updated:
            updated = updated.replace(
                "const app = express();",
                'const helmet = require("helmet");\nconst app = express();\napp.use(helmet());',
                1,
            )

        if "FEATURE_ROUTES_START" not in updated:
            updated = updated.replace(
                "module.exports = app;",
                "// FEATURE_ROUTES_START\n// FEATURE_ROUTES_END\n\nmodule.exports = app;",
                1,
            )

        if "express-rate-limit" not in updated:
            updated = updated.replace(
                "module.exports = app;",
                'const rateLimit = require("express-rate-limit");\n'
                "const apiLimiter = rateLimit({\n"
                "  windowMs: 15 * 60 * 1000,\n"
                "  max: 100,\n"
                "  standardHeaders: true,\n"
                "  legacyHeaders: false,\n"
                "});\n"
                'app.use("/api/", apiLimiter);\n\n'
                "module.exports = app;",
                1,
            )

        if "err.stack" not in updated:
            updated = updated.replace(
                "module.exports = app;",
                "app.use((err, req, res, next) => {\n"
                "  console.error(err.stack);\n"
                "  const status = err.status || 500;\n"
                '  res.status(status).json({ error: { message: err.message || "Internal Server Error" } });\n'
                "});\n\n"
                "module.exports = app;",
                1,
            )

        if updated == content:
            return False

        path.write_text(updated, encoding="utf-8")
        return True

    def _upgrade_server_server_js(self, path: Path) -> bool:
        """
        Add a guarded mongoose.connect(...) startup step to an existing
        server/src/server.js. Wholesale-replaces only if the file is
        provably still the exact, untouched original scaffold; otherwise
        skips (logging a warning) rather than risk corrupting a boot
        sequence a feature has already customized -- unlike app.js's
        stable require/export anchors, a hand-modified server.js has no
        equally reliable universal insertion point to anchor on.
        """
        content = path.read_text(encoding="utf-8")

        if content == _LEGACY_SERVER_SERVER_JS_V1:
            path.write_text(MERN_SERVER_SERVER_JS, encoding="utf-8")
            return True

        if "mongoose.connect" in content:
            return False

        logger.warning(
            "server/src/server.js has already been customized and does not call "
            "mongoose.connect -- skipping automatic DB-connection backfill; add it "
            "manually if this project needs one."
        )
        return False

    def _upgrade_client_app_jsx(self, path: Path) -> bool:
        """
        Add a FEATURE_LINKS marker pair inside HomePage's <nav> so every
        feature's coding step has a stable place to add a real <Link> to
        its new page. Without this, a feature's Coder Agent run correctly
        adds a new <Route> but nothing ever links to it -- confirmed
        directly in the real e-commerce-platform and taskflow projects,
        both of which only ever showed the static placeholder HomePage
        because their new routes ("/login", "/tasks/:taskId") were never
        reachable from "/".

        Wholesale-replaces only if the file is provably still the exact,
        untouched original scaffold. Otherwise anchors a targeted
        insertion on HomePage's known placeholder paragraph (present in
        every version to date, since no feature has touched HomePage
        itself so far -- only the <Routes> block) -- if that anchor isn't
        found, skips with a warning rather than risk corrupting a
        HomePage a project has customized beyond recognition, matching
        _upgrade_server_server_js's same fallback philosophy.
        """
        content = path.read_text(encoding="utf-8")

        if content == _LEGACY_CLIENT_APP_JSX_V1:
            path.write_text(MERN_CLIENT_APP_JSX, encoding="utf-8")
            return True

        if "FEATURE_LINKS_START" in content:
            return False

        anchor = "<p>Feature pages are registered as routes below.</p>\n    </div>"
        if anchor not in content:
            logger.warning(
                "client/src/App.jsx's HomePage has diverged too far from the scaffold "
                "template to safely add a navigation anchor -- skipping. Add a "
                "{/* FEATURE_LINKS_START */} / {/* FEATURE_LINKS_END */} marker pair inside "
                "HomePage manually if this project needs one."
            )
            return False

        updated = content.replace(
            anchor,
            "<p>Feature pages are registered as routes below.</p>\n"
            "      <nav>\n"
            "        <ul>\n"
            "          {/* FEATURE_LINKS_START */}\n"
            "          {/* FEATURE_LINKS_END */}\n"
            "        </ul>\n"
            "      </nav>\n"
            "    </div>",
            1,
        )

        if 'import { Routes, Route } from "react-router-dom";' in updated:
            updated = updated.replace(
                'import { Routes, Route } from "react-router-dom";',
                'import { Routes, Route, Link } from "react-router-dom";',
                1,
            )

        path.write_text(updated, encoding="utf-8")
        return True

    def start_feature_branch(self, project_id: str, feature_id: str) -> str:
        """
        Create (or reset) `feature/{feature_slug}` from main and check it out.

        Returns the branch name.
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)

        repo.git.checkout(MAIN_BRANCH)

        if branch_name in [head.name for head in repo.heads]:
            repo.git.branch("-D", branch_name)

        repo.git.checkout("-b", branch_name)

        return branch_name

    def resume_feature_branch(self, project_id: str, feature_id: str) -> str:
        """
        Check out an EXISTING feature branch without resetting it -- for
        revision runs (CoderAgent.revise) that must build on top of prior
        work, not discard it. Unlike start_feature_branch (always deletes
        and recreates from main), this only ever checks out what's already
        there, with one fallback (see below).

        Real, confirmed bug: a revision only ever reaches this method after
        CoderAgent.revise() has already confirmed a real prior CODE_PLAN
        artifact exists for this feature (there is genuinely something to
        revise) -- but the feature's own branch is routinely gone by the
        time a LATER revision is requested, most commonly because it was
        already approved, merged into main via merge_feature_branch (a real
        `--no-ff` merge), and cleanly deleted as that method's own
        established post-merge cleanup. That's normal git hygiene, not
        evidence the feature was never coded -- the code is still fully
        present, merged into main. The old behavior (raise unconditionally)
        treated this completely ordinary case identically to "this feature
        was never coded at all," permanently blocking any further revision
        (e.g. a security-driven fix) on every feature that had ever been
        successfully merged -- confirmed live against a real feature whose
        own merge report showed `Verification: PASSED` and whose code was
        genuinely sitting on main the whole time.

        Fixed: when the feature's own branch is missing, fall back to
        branching fresh from main's CURRENT tip instead of raising --
        main already has this feature's real, merged code in the case
        above (a `--no-ff` merge keeps the feature branch's own tip
        reachable as an ancestor, so main's tree already matches what the
        feature branch had), so this recreates the same real working-tree
        content resuming the original branch would have, not a fresh
        regeneration. Genuinely never-coded features can't reach this
        method at all (revise()'s own precondition catches that first), so
        there is no case where falling back here silently starts from an
        empty/wrong base.
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)

        if branch_name not in [head.name for head in repo.heads]:
            repo.git.checkout(MAIN_BRANCH)
            repo.git.checkout("-b", branch_name)
            return branch_name

        repo.git.checkout(branch_name)

        return branch_name

    def commit_changes(self, project_id: str, feature_id: str, message: str) -> bool:
        """
        Stage and commit everything currently on the feature branch's working
        tree. Returns False (no-op) if there is nothing to commit.

        The coding loop's tools (write_file/apply_patch/run_shell) only ever
        touch the working tree -- they never commit. diff_against_main() and
        merge_feature_branch() both operate on committed history, so this is
        the deterministic step between "the agentic loop finished" and
        "there is a diff/mergeable commit to review."
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)

        if repo.active_branch.name != branch_name:
            repo.git.checkout(branch_name)

        if not repo.is_dirty(untracked_files=True):
            return False

        repo.git.add(A=True)
        repo.index.commit(message)

        return True

    def diff_against_main(self, project_id: str, feature_id: str) -> dict[str, Any]:
        """
        Return a structured diff of the feature branch against main:
            {
                "added": [...], "modified": [...], "deleted": [...],
                "diff_text": "<unified diff>",
            }

        This is computed deterministically from git, never from an LLM's self-report.
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)

        name_status = repo.git.diff(
            f"{MAIN_BRANCH}...{branch_name}", "--name-status"
        )
        diff_text = repo.git.diff(f"{MAIN_BRANCH}...{branch_name}")

        return {**self._parse_name_status(name_status), "diff_text": diff_text}

    def get_touched_files(
        self, project_id: str, feature_id: str, since: str = MAIN_BRANCH
    ) -> dict[str, list[str]]:
        """
        Return {"added": [...], "modified": [...], "deleted": [...]} comparing
        the feature branch's CURRENT WORKING TREE (including uncommitted,
        even still-untracked changes) against `since` (main's tip by default).

        Unlike diff_against_main's committed-history-only triple-dot
        comparison, this is accurate mid-coding-loop, before commit_changes
        has run -- which is what makes it usable as a self-check tool
        during an agentic attempt (list_unimplemented_planned_files),
        not only after the loop has already finished.

        `since` matters because comparing against `main` unconditionally is
        only correct for a file's FIRST-EVER revision. Once any earlier
        revision has touched a file, it permanently differs from `main`
        forever after -- so a caller that wants to know "did THIS attempt/
        revision touch this file" must pass the SHA the current attempt
        actually started from, or every attempt after the first will look
        like it touched every previously-touched file even if it changed
        nothing at all (confirmed root cause of a real false "verification
        passed" on a no-op revision).

        Stages everything first (git add -A) so a brand-new file the coding
        loop just wrote via write_file, still untracked, is correctly seen
        as "added" -- a plain `git diff <ref>` silently ignores untracked
        files entirely. This mirrors exactly what commit_changes will do
        moments later regardless, so it introduces no new inconsistency.

        NOT read-only: the `git add -A` above is a real, persistent side
        effect on the repo's index (it stays staged after this call returns,
        regardless of whether the caller ends up committing). This matters
        because this method is also the implementation behind
        list_unimplemented_planned_files, a tool exposed to the model as a
        "self-check" -- do not assume a future caller of this method (or that
        tool) leaves the working tree/index untouched.
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)

        if repo.active_branch.name != branch_name:
            repo.git.checkout(branch_name)

        if repo.is_dirty(untracked_files=True):
            repo.git.add(A=True)

        name_status = repo.git.diff("--cached", since, "--name-status")
        return self._parse_name_status(name_status)

    def _parse_name_status(self, name_status: str) -> dict[str, list[str]]:
        added, modified, deleted = [], [], []

        for line in name_status.splitlines():
            if not line.strip():
                continue

            status, _, path = line.partition("\t")

            if status.startswith("A"):
                added.append(path)
            elif status.startswith("D"):
                deleted.append(path)
            else:
                modified.append(path)

        return {"added": added, "modified": modified, "deleted": deleted}

    def _find_merge_commit_for_branch(self, repo: Repo, branch_name: str):
        """
        Searches main's own history for the real, 2-parent commit merge_feature_branch itself
        wrote (message exactly f"Merge {branch_name} into main") -- this repo has no separate
        merge-commit-sha ledger, so the commit message IS the ledger. iter_commits is newest-first
        by default, so the first match is the MOST RECENT merge of this branch. Returns None if
        none exists (e.g. this branch has never actually been merged).
        """
        expected_message = f"Merge {branch_name} into main"
        for commit in repo.iter_commits(MAIN_BRANCH):
            if len(commit.parents) == 2 and commit.message.strip() == expected_message:
                return commit
        return None

    def merge_feature_branch(self, project_id: str, feature_id: str) -> None:
        """
        Merge the approved feature branch into main and delete the branch.

        Real git gotcha, found live (a human revoked a Coder Agent approval -- see
        undo_merge_feature_branch -- then re-approved the SAME code with no new commits on the
        feature branch): a plain `git merge --no-ff branch` here would silently no-op
        ("Already up to date") instead of actually re-applying the branch's changes. Reverting a
        merge does NOT remove the merged branch's commits from main's ancestry graph -- they're
        still there, just with their effect undone by the revert commit -- so git's ancestry-based
        merge algorithm correctly-but-unhelpfully concludes "nothing new to merge" even though the
        real file content is missing from main's working tree. The artifact would end up marked
        approved with the code never actually landing on main -- a real, silent data/reality
        mismatch, not just a git-internals curiosity. Detected by checking whether the branch tip
        is already an ancestor of main; if so, the fix (per `git revert`'s own manual, "Reverting
        a merge commit") is to revert the EARLIER REVERT itself first, which restores the original
        merged content, before proceeding exactly as normal.
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)

        repo.git.checkout(MAIN_BRANCH)

        branch_head = repo.heads[branch_name] if branch_name in [h.name for h in repo.heads] else None
        already_an_ancestor = False
        if branch_head is not None:
            try:
                repo.git.merge_base("--is-ancestor", branch_head.commit.hexsha, repo.head.commit.hexsha)
                already_an_ancestor = True
            except GitCommandError:
                already_an_ancestor = False

        if already_an_ancestor:
            merge_commit = self._find_merge_commit_for_branch(repo, branch_name)
            revert_commit = None
            if merge_commit is not None:
                expected_revert_prefix = f'Revert "Merge {branch_name} into main"'
                for commit in repo.iter_commits(MAIN_BRANCH):
                    if commit.message.strip().startswith(expected_revert_prefix):
                        revert_commit = commit
                        break

            if revert_commit is None:
                raise ValueError(
                    f"{branch_name}'s tip is already an ancestor of main with no matching "
                    "revert commit found -- refusing to guess how to re-merge it."
                )

            # Un-reverts the earlier revert, restoring the branch's real content on main --
            # NOT a second normal merge (which would still no-op for the ancestry reason above).
            repo.git.revert(revert_commit.hexsha, "--no-edit")
        else:
            try:
                repo.git.merge(branch_name, "--no-ff", "-m", f"Merge {branch_name} into main")
            except GitCommandError:
                repo.git.merge("--abort")
                raise

        repo.git.branch("-d", branch_name)

    def discard_feature_branch(self, project_id: str, feature_id: str) -> None:
        """
        Discard a rejected feature branch's changes and return to main.
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)

        repo.git.checkout(MAIN_BRANCH)

        if branch_name in [head.name for head in repo.heads]:
            repo.git.branch("-D", branch_name)

    def undo_merge_feature_branch(self, project_id: str, feature_id: str) -> str | None:
        """
        Reverses a prior merge_feature_branch call for real, real-only revoked approval (a human
        approved the Coder Agent's output, which merged it, then asked to revoke that approval to
        request changes) -- recreates the feature branch at its pre-merge tip and reverts the
        merge on main, WITHOUT rewriting history (a plain `git revert`, never a reset/force-push),
        so this is safe to call even if main has since gained other, unrelated commits.

        Finds the merge commit by searching main's own history for a real, 2-parent commit whose
        message is exactly the one merge_feature_branch itself writes
        (f"Merge {branch_name} into main") -- this repo has no separate merge-commit-sha ledger,
        so the commit message IS the ledger. Returns None (a safe no-op, not an error) if no such
        commit is found -- e.g. the artifact was approved but the merge itself already failed and
        was logged, not actually applied (see approval_service.submit_approval's own broad
        except around merge_approved_feature).

        Returns the restored branch name on success.
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)

        merge_commit = self._find_merge_commit_for_branch(repo, branch_name)
        if merge_commit is None:
            return None

        if branch_name not in [head.name for head in repo.heads]:
            repo.create_head(branch_name, merge_commit.parents[1])

        repo.git.checkout(MAIN_BRANCH)
        repo.git.revert(merge_commit.hexsha, "-m", "1", "--no-edit")

        return branch_name

    def export_zip(self, project_id: str, ref: str) -> bytes:
        """
        Zip a git ref's tree (committed content only -- uncommitted working-tree changes are
        never included) into an in-memory archive, excluding .git itself.

        Reads directly from the commit's tree object (repo.commit(ref).tree.traverse()) rather
        than checking the ref out first -- this can be called regardless of whatever branch is
        currently checked out, with no risk of disturbing it (e.g. a coding loop that might be
        mid-run on a different branch at the same time).
        """
        repo = self.ensure_project_repo(project_id)

        try:
            commit = repo.commit(ref)
        except Exception as error:
            raise ValueError(f"No such ref '{ref}' in this project's repo.") from error

        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in commit.tree.traverse():
                if item.type != "blob":
                    continue

                archive.writestr(item.path, item.data_stream.read())

        return buffer.getvalue()

    def export_feature_code_zip(self, project_id: str, feature_id: str) -> bytes:
        """
        Zip a feature's own code -- its branch if it still exists (pre-merge/pre-approval, so a
        reviewer can try the code locally before deciding), otherwise falls back to `main` (the
        branch is deleted once merged, per merge_feature_branch).
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)
        ref = branch_name if branch_name in [head.name for head in repo.heads] else MAIN_BRANCH

        return self.export_zip(project_id, ref)

    def export_feature_code_with_extra_files_zip(
        self, project_id: str, feature_id: str, extra_files: list[tuple[str, bytes]]
    ) -> bytes:
        """
        Same as export_feature_code_zip, but with extra (path, bytes) pairs appended into the
        same archive after the real git-tree content -- used to bundle a feature's generated
        code together with its QA report. Kept as a separate function (rather than adding an
        optional parameter to export_feature_code_zip) so the Coder stage's existing plain
        code-only download is completely unaffected.
        """
        repo = self.ensure_project_repo(project_id)
        branch_name = self._feature_branch_name(feature_id)
        ref = branch_name if branch_name in [head.name for head in repo.heads] else MAIN_BRANCH

        try:
            commit = repo.commit(ref)
        except Exception as error:
            raise ValueError(f"No such ref '{ref}' in this project's repo.") from error

        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in commit.tree.traverse():
                if item.type != "blob":
                    continue

                archive.writestr(item.path, item.data_stream.read())

            for path, data in extra_files:
                archive.writestr(path, data)

        return buffer.getvalue()


workspace_service = WorkspaceService()
