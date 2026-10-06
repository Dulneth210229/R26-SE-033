"""
Sandbox / shell execution service.

The Coder Agent (and later Security/QA agents) need to run real shell commands
(npm install, npm run build, npm test, npm audit, ...) against a project's
generated codebase. This must never run directly on the host: it runs inside a
disposable Docker container with the project's workspace bind-mounted.

This service never raises for a failed *command* -- a nonzero exit code, a
build failure, or a timeout are all returned as data ({exit_code, stdout,
stderr}) so an agentic loop can read the failure and try to self-correct.
Only setup problems (e.g. Docker itself unreachable) raise, since there is
nothing an agent loop could do about that.

SANDBOX_IMAGE is a custom image (docker/coder-sandbox.Dockerfile), based on
node:20 rather than node:20-slim -- -slim ships without a git binary, which
silently broke the `git status`/`git diff` self-check the Coder Agent's
system prompt encourages using (always exit 127). The image also bakes in
@babel/parser globally so the check_syntax tool can validate JSX before a
project's own `npm install` has ever run. Build it once with:
    docker build -t autoforge-coder-sandbox:latest -f docker/coder-sandbox.Dockerfile .
"""

import time
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException

from app.services.workspace_service import workspace_service

SANDBOX_IMAGE = "autoforge-coder-sandbox:latest"
DEFAULT_TIMEOUT_SECONDS = 120

# `next build`'s bundling + full TypeScript typecheck routinely exceeds the
# Vite-era 1g default -- a Docker OOM kill surfaces as an undiagnosable bare
# exit 137 with no clear signal it was a memory limit, not a real build
# failure. Raised for both run_command and start_background_service; either
# can be asked to run `next build`/`next start`.
DEFAULT_MEM_LIMIT = "2g"

# Container label key used to tag every long-running preview container
# (preview_service.py) so an orphan sweep (e.g. after a --reload restart
# drops the in-memory preview registry) can find and clean them up by
# listing containers with this label instead of relying on in-process state.
PREVIEW_CONTAINER_LABEL = "autoforge.preview.feature_id"


class SandboxService:
    """
    Runs shell commands for a project inside a disposable, isolated container.
    """

    def __init__(self, image: str = SANDBOX_IMAGE):
        self.image = image

    def run_command(
        self,
        project_id: str,
        command: str,
        cwd: str = ".",
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        mem_limit: str = DEFAULT_MEM_LIMIT,
    ) -> dict[str, Any]:
        """
        Run `command` inside a fresh container with the project's workspace
        mounted read-write at /workspace.

        Returns {"exit_code": int, "stdout": str, "stderr": str}. Never raises
        for command failure or timeout.
        """
        repo_path = workspace_service.get_repo_path(project_id)
        repo_path.mkdir(parents=True, exist_ok=True)

        working_dir = "/workspace" if cwd in (".", "") else f"/workspace/{cwd.lstrip('/')}"

        try:
            client = docker.from_env()
        except DockerException as error:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": f"Sandbox unavailable: could not reach Docker daemon: {error}",
            }

        container = None

        try:
            container = client.containers.run(
                self.image,
                command=["sh", "-c", command],
                working_dir=working_dir,
                volumes={str(Path(repo_path).resolve()): {"bind": "/workspace", "mode": "rw"}},
                mem_limit=mem_limit,
                detach=True,
            )

            try:
                result = container.wait(timeout=timeout)
                exit_code = result.get("StatusCode", 1)
                timed_out = False
            except Exception:
                container.kill()
                exit_code = 124  # conventional timeout exit code
                timed_out = True

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            if timed_out:
                stderr = (stderr + f"\n[sandbox] command timed out after {timeout}s").strip()

            return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}

        except DockerException as error:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": f"Sandbox execution error: {error}",
            }

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass

    def start_background_service(
        self,
        project_id: str,
        command: str,
        cwd: str,
        container_port: int,
        mem_limit: str = DEFAULT_MEM_LIMIT,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Start `command` in a detached container that keeps running (unlike
        run_command, which waits for the command to exit) with
        `container_port` published to an available host port. For
        long-running processes like `next start`/`vite preview` that never
        exit on their own -- e.g. the Coder Agent's runtime-render check and
        the live preview feature, both of which need an actually-running
        server for Playwright/a human's browser to navigate to.

        `labels` (e.g. {PREVIEW_CONTAINER_LABEL: feature_id}) tags the
        container so a caller (preview_service's orphan sweep) can find and
        clean up containers left behind by a process restart, without
        needing its own in-memory registry to have survived.

        Returns {"container": <docker Container>, "host_port": int}. The
        caller must call stop_background_service(container) when done --
        this does not clean up after itself the way run_command does,
        since the whole point is that it keeps running.

        Raises RuntimeError if Docker is unreachable or the container
        fails to start -- unlike run_command, there is no meaningful
        "returned as data" failure mode for a service that never produces
        a normal exit code.
        """
        repo_path = workspace_service.get_repo_path(project_id)
        repo_path.mkdir(parents=True, exist_ok=True)

        working_dir = "/workspace" if cwd in (".", "") else f"/workspace/{cwd.lstrip('/')}"

        try:
            client = docker.from_env()
        except DockerException as error:
            raise RuntimeError(f"Sandbox unavailable: could not reach Docker daemon: {error}") from error

        try:
            container = client.containers.run(
                self.image,
                command=["sh", "-c", command],
                working_dir=working_dir,
                volumes={str(Path(repo_path).resolve()): {"bind": "/workspace", "mode": "rw"}},
                mem_limit=mem_limit,
                ports={f"{container_port}/tcp": None},  # None = let Docker assign a free host port
                labels=labels or {},
                detach=True,
            )
        except DockerException as error:
            raise RuntimeError(f"Sandbox execution error: {error}") from error

        # Docker publishes the port as soon as the container's network is up --
        # this does not wait for the process inside to actually bind it -- but
        # container.attrs is a point-in-time snapshot from container.reload(),
        # and immediately after client.containers.run() returns, the daemon has
        # not always finished recording that mapping yet. Poll briefly instead
        # of trusting a single reload (confirmed directly: a bare reload right
        # after run() reported no port bindings for a container that, moments
        # later, was already running with its port correctly published).
        port_bindings = None
        for _ in range(10):
            container.reload()
            port_bindings = container.attrs["NetworkSettings"]["Ports"].get(f"{container_port}/tcp")
            if port_bindings:
                break
            if container.status == "exited":
                break
            time.sleep(0.3)

        if not port_bindings:
            logs = container.logs().decode("utf-8", errors="replace")
            self.stop_background_service(container)
            raise RuntimeError(
                f"Container started but port {container_port} was not published -- "
                f"the process may have exited immediately. Container status: "
                f"{container.status}. Logs:\n{logs}"
            )

        host_port = int(port_bindings[0]["HostPort"])

        return {"container": container, "host_port": host_port}

    def stop_background_service(self, container: Any) -> None:
        """Kill and remove a container started by start_background_service."""
        try:
            container.kill()
        except DockerException:
            pass
        finally:
            try:
                container.remove(force=True)
            except DockerException:
                pass

    def find_containers_by_label(self, label_key: str) -> list[Any]:
        """
        List every container (running or not) carrying `label_key`, for an
        orphan sweep (preview_service's startup cleanup) that must find
        containers left behind by a prior process's in-memory registry
        having been dropped (e.g. a `--reload` restart) -- returns an empty
        list, never raises, if Docker itself is unreachable.
        """
        try:
            client = docker.from_env()
            return client.containers.list(all=True, filters={"label": label_key})
        except DockerException:
            return []


sandbox_service = SandboxService()
