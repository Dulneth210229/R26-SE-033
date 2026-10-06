"""
Live preview service.

Cursor-style live preview of the Coder Agent's generated Next.js app in the
frontend's Result panel: explicit Start/Stop, never automatic, built entirely
on the existing, unmodified sandbox_service.start_background_service/
stop_background_service (already fully generic).

State is a plain in-memory registry (ephemeral process state -- same
precedent as graph_orchestrator_service's in-memory per-thread state, not
persisted to Mongo): {feature_id: {project_id, container, host_port,
built_commit_sha, started_at}}. This means a backend restart drops all
knowledge of running preview containers -- sweep_orphaned_containers() (call
this once at app startup) finds and stops any container still carrying the
preview label so a restart never leaves an orphaned container running
forever.

Concurrency rule: two DIFFERENT features of the SAME project can never
preview at once, since every container mounts the one shared working tree
read-write and `.next/`'s build output isn't branch-scoped -- starting a
second feature's preview while a sibling's is running is refused (409) with
the conflicting feature named, not silently killed. The SAME feature
restarting its own preview is fine (stops the old container, starts fresh).
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.in_memory_store import store
from app.services.sandbox_service import PREVIEW_CONTAINER_LABEL, sandbox_service
from app.services.workspace_service import workspace_service
from app.utils.logger import get_logger

logger = get_logger(__name__)

PREVIEW_CONTAINER_PORT = 3000
PREVIEW_START_COMMAND = f"npx next start -H 0.0.0.0 -p {PREVIEW_CONTAINER_PORT}"
READINESS_POLL_ATTEMPTS = 20
READINESS_POLL_INTERVAL_SECONDS = 1


class PreviewNotBuiltError(Exception):
    """Raised when Start is requested but no .next build exists yet for this workspace."""


class PreviewUnsupportedStackError(Exception):
    """
    Raised when Start is requested for a project whose workspace is frozen
    on the legacy MERN scaffold (see workspace_service._detect_stack) --
    it will never produce a .next build no matter how many times the Coder
    Agent runs, since re-running it against a MERN-detected repo still only
    ever generates MERN code. Kept distinct from PreviewNotBuiltError (whose
    own message tells a human to "run the Coder Agent again," which is
    actively wrong advice here) so the frontend can show accurate guidance
    instead of implying a rebuild would fix it.
    """


class PreviewConflictError(Exception):
    """Raised when a different feature of the same project already has a preview running."""

    def __init__(self, conflicting_feature_id: str, conflicting_feature_name: str):
        self.conflicting_feature_id = conflicting_feature_id
        self.conflicting_feature_name = conflicting_feature_name
        super().__init__(
            f"Feature '{conflicting_feature_name}' ({conflicting_feature_id}) already has a "
            "live preview running for this project -- stop it before previewing a different "
            "feature (they share the same working tree)."
        )


@dataclass
class _PreviewSession:
    project_id: str
    container: Any
    host_port: int
    built_commit_sha: str
    started_at: datetime


class PreviewService:
    """
    Manages live-preview containers for the Coder Agent's generated Next.js app.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _PreviewSession] = {}

    def start_preview(self, feature_id: str) -> dict[str, Any]:
        """
        Start (or restart) a live preview for this feature. Raises
        PreviewNotBuiltError if no .next build exists yet for the current
        checkout, PreviewConflictError if a different feature of the same
        project already has one running.
        """
        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")

        project_id = feature["project_id"]

        conflict = self._find_conflicting_feature(project_id, exclude_feature_id=feature_id)
        if conflict:
            conflicting_feature = store.features.get(conflict) or {}
            raise PreviewConflictError(conflict, conflicting_feature.get("feature_name", conflict))

        # Restart semantics for the SAME feature -- stop whatever's running
        # first rather than layering a second container on top.
        if feature_id in self._sessions:
            self.stop_preview(feature_id)

        repo_path = workspace_service.get_repo_path(project_id)

        if (repo_path / ".git").exists() and workspace_service._detect_stack(repo_path) == "mern":
            raise PreviewUnsupportedStackError(
                "This project's generated app is still on the legacy MERN stack (from before "
                "the Next.js migration) -- live preview only supports Next.js projects, and "
                "re-running the Coder Agent here will not change that. Create a new project to "
                "get a Next.js app with live preview support."
            )

        build_id_path = repo_path / ".next" / "BUILD_ID"

        if not build_id_path.exists():
            raise PreviewNotBuiltError(
                "No build found for this feature yet -- run the Coder Agent (or a revision) "
                "first, then try previewing again."
            )

        built_commit_sha = self._current_head_sha(project_id)

        service = sandbox_service.start_background_service(
            project_id=project_id,
            command=PREVIEW_START_COMMAND,
            cwd=".",
            container_port=PREVIEW_CONTAINER_PORT,
            labels={PREVIEW_CONTAINER_LABEL: feature_id},
        )

        host_port = service["host_port"]
        container = service["container"]

        if not self._wait_until_ready(host_port):
            sandbox_service.stop_background_service(container)
            raise PreviewNotBuiltError(
                "The preview server did not become reachable in time -- see backend logs and "
                "try again."
            )

        self._sessions[feature_id] = _PreviewSession(
            project_id=project_id,
            container=container,
            host_port=host_port,
            built_commit_sha=built_commit_sha,
            started_at=datetime.now(timezone.utc),
        )

        return self.get_status(feature_id)

    def get_status(self, feature_id: str) -> dict[str, Any]:
        """
        Returns {"status": "stopped"|"running"|"stale", "preview_url": str | None,
        "started_at": str | None}.

        "stale" means the workspace's checked-out commit has moved on since
        this preview was started (e.g. a new Coder Agent revision landed on
        the same feature) -- the running container is very likely still
        serving the OLD build, since `.next/` isn't rebuilt just because a
        new commit exists. The container is left running (stop still works
        normally) -- only the reported status changes, so the frontend can
        prompt "rebuild and restart the preview" instead of confidently
        showing stale output as current.
        """
        session = self._sessions.get(feature_id)

        if not session:
            return {"status": "stopped", "preview_url": None, "started_at": None}

        current_sha = self._current_head_sha(session.project_id)
        status = "running" if current_sha == session.built_commit_sha else "stale"

        return {
            "status": status,
            "preview_url": f"http://localhost:{session.host_port}",
            "started_at": session.started_at.isoformat(),
        }

    def stop_preview(self, feature_id: str) -> None:
        """Idempotent -- a no-op if this feature has no preview running."""
        session = self._sessions.pop(feature_id, None)

        if session:
            sandbox_service.stop_background_service(session.container)

    def stop_preview_if_running(self, feature_id: str) -> None:
        """
        Same as stop_preview, but named for call sites (CoderAgent.run/revise)
        that stop a preview as a side effect of something else starting, not
        because a human asked to stop it -- the working tree a running
        preview depends on is about to change underneath it.
        """
        self.stop_preview(feature_id)

    def sweep_orphaned_containers(self) -> int:
        """
        Stop and remove every container still carrying the preview label,
        regardless of this process's own (empty, just-started) in-memory
        registry -- call once at backend startup to clean up containers a
        prior process's `--reload` restart left running. Returns the number
        of containers stopped.
        """
        containers = sandbox_service.find_containers_by_label(PREVIEW_CONTAINER_LABEL)

        for container in containers:
            logger.info("Stopping orphaned preview container %s on startup.", container.id)
            sandbox_service.stop_background_service(container)

        return len(containers)

    def find_running_feature_for_project(self, project_id: str) -> str | None:
        """
        Which feature (if any) of this project currently has a live preview running.
        The service's own invariant -- two different features of the same project can never
        preview at once (_find_conflicting_feature enforces this on start) -- guarantees at most
        one candidate, so this is a safe, unambiguous "which one" lookup for a project-scoped
        caller that doesn't have (and shouldn't need) a specific feature_id in hand, e.g. the
        database-connection routes restarting whatever preview happens to be running after a
        human changes the project's saved MongoDB URI.
        """
        for feature_id, session in self._sessions.items():
            if session.project_id == project_id:
                return feature_id
        return None

    def restart_if_running(self, feature_id: str) -> bool:
        """
        Restart this feature's live preview if one is currently running (a no-op, returns False,
        if it's already stopped) -- used whenever something changed that a running preview
        container needs to pick up (a new Coder Agent revision landing on the same feature, or a
        human saving/clearing this project's MongoDB connection string) but isn't itself a human
        explicitly clicking Stop. Was CoderAgent._maybe_restart_running_preview; relocated here
        since it only ever touches preview_service and a second, non-CoderAgent caller
        (the database-connection routes) now needs the identical logic -- better one real
        implementation on the service that owns the state than a third reimplementation
        elsewhere.
        """
        if self.get_status(feature_id)["status"] == "stopped":
            return False

        self.start_preview(feature_id)
        return True

    def _find_conflicting_feature(self, project_id: str, exclude_feature_id: str) -> str | None:
        for other_feature_id, session in self._sessions.items():
            if other_feature_id == exclude_feature_id:
                continue
            if session.project_id == project_id:
                return other_feature_id
        return None

    def _current_head_sha(self, project_id: str) -> str:
        repo = workspace_service.ensure_project_repo(project_id)
        return repo.head.commit.hexsha

    def _wait_until_ready(self, host_port: int) -> bool:
        url = f"http://localhost:{host_port}"

        for _ in range(READINESS_POLL_ATTEMPTS):
            try:
                urllib.request.urlopen(url, timeout=2)
                return True
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(READINESS_POLL_INTERVAL_SECONDS)

        return False


preview_service = PreviewService()
