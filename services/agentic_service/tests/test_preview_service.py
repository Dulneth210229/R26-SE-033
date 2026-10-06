"""
Unit tests for preview_service.py's pure orchestration logic: conflict
detection, stale/running/stopped status derivation, not-built refusal, and
idempotent stop. Mocks sandbox_service (Docker) and workspace_service (git)
entirely -- no Docker, no real git repo -- since the actual container
start/stop mechanism is already covered by sandbox_service's own real,
Docker-backed tests (test_render_checker.py).
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.in_memory_store import store
from app.services.preview_service import (
    PreviewConflictError,
    PreviewNotBuiltError,
    PreviewService,
    PreviewUnsupportedStackError,
)
from app.utils.id_generator import generate_id


@pytest.fixture
def feature_and_project():
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": "Preview Test Project"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Preview Test Feature",
    }

    yield project_id, feature_id

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})


@pytest.fixture
def service():
    return PreviewService()


def _mock_repo(head_sha: str) -> MagicMock:
    repo = MagicMock()
    repo.head.commit.hexsha = head_sha
    return repo


def test_start_raises_when_no_build_exists(service, feature_and_project, tmp_path):
    _project_id, feature_id = feature_and_project

    with patch("app.services.preview_service.workspace_service") as mock_ws:
        mock_ws.get_repo_path.return_value = tmp_path  # empty dir, no .next/BUILD_ID

        with pytest.raises(PreviewNotBuiltError):
            service.start_preview(feature_id)


def test_start_raises_for_unknown_feature(service):
    with pytest.raises(ValueError):
        service.start_preview("feature_does_not_exist")


def test_start_raises_unsupported_stack_for_a_legacy_mern_project(service, feature_and_project, tmp_path):
    # Reproduces a real, confirmed reported bug: a project frozen on the
    # legacy MERN scaffold (from before the Next.js migration) will NEVER
    # produce a .next build, so the generic "run the Coder Agent again"
    # advice from PreviewNotBuiltError is actively wrong here -- this must
    # be a distinct, more accurate error.
    _project_id, feature_id = feature_and_project
    (tmp_path / ".git").mkdir()
    (tmp_path / "server" / "src").mkdir(parents=True)
    (tmp_path / "server" / "src" / "app.js").write_text("", encoding="utf-8")

    with patch("app.services.preview_service.workspace_service") as mock_ws:
        mock_ws.get_repo_path.return_value = tmp_path
        mock_ws._detect_stack.return_value = "mern"

        with pytest.raises(PreviewUnsupportedStackError):
            service.start_preview(feature_id)


def test_start_still_raises_not_built_for_a_genuine_nextjs_project_with_no_build_yet(
    service, feature_and_project, tmp_path
):
    # A real (not-yet-built) Next.js project must still get the original,
    # accurate "run the Coder Agent" guidance -- only a MERN-detected repo
    # gets the different message.
    _project_id, feature_id = feature_and_project
    (tmp_path / ".git").mkdir()

    with patch("app.services.preview_service.workspace_service") as mock_ws:
        mock_ws.get_repo_path.return_value = tmp_path
        mock_ws._detect_stack.return_value = "nextjs"

        with pytest.raises(PreviewNotBuiltError):
            service.start_preview(feature_id)


def test_start_succeeds_and_records_session(service, feature_and_project, tmp_path):
    _project_id, feature_id = feature_and_project
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("abc123", encoding="utf-8")

    with patch("app.services.preview_service.workspace_service") as mock_ws, patch(
        "app.services.preview_service.sandbox_service"
    ) as mock_sandbox:
        mock_ws.get_repo_path.return_value = tmp_path
        mock_ws.ensure_project_repo.return_value = _mock_repo("sha-1")
        mock_sandbox.start_background_service.return_value = {
            "container": MagicMock(),
            "host_port": 54321,
        }

        with patch.object(service, "_wait_until_ready", return_value=True):
            result = service.start_preview(feature_id)

    assert result["status"] == "running"
    assert result["preview_url"] == "http://localhost:54321"
    assert result["started_at"] is not None


def test_status_reports_stopped_when_never_started(service, feature_and_project):
    _project_id, feature_id = feature_and_project
    assert service.get_status(feature_id) == {"status": "stopped", "preview_url": None, "started_at": None}


def test_status_reports_stale_when_head_moved_on(service, feature_and_project, tmp_path):
    _project_id, feature_id = feature_and_project
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("abc123", encoding="utf-8")

    with patch("app.services.preview_service.workspace_service") as mock_ws, patch(
        "app.services.preview_service.sandbox_service"
    ) as mock_sandbox:
        mock_ws.get_repo_path.return_value = tmp_path
        mock_ws.ensure_project_repo.return_value = _mock_repo("sha-1")
        mock_sandbox.start_background_service.return_value = {
            "container": MagicMock(),
            "host_port": 54321,
        }

        with patch.object(service, "_wait_until_ready", return_value=True):
            service.start_preview(feature_id)

        # Simulate a new commit landing on the feature branch after the
        # preview was started (e.g. a fresh Coder Agent revision).
        mock_ws.ensure_project_repo.return_value = _mock_repo("sha-2")

        status = service.get_status(feature_id)

    assert status["status"] == "stale"


def test_starting_a_second_feature_of_the_same_project_is_blocked(service, feature_and_project, tmp_path):
    project_id, feature_id = feature_and_project
    other_feature_id = generate_id("feature")
    store.features[other_feature_id] = {
        "project_id": project_id,
        "feature_id": other_feature_id,
        "feature_name": "Sibling Feature",
    }
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("abc123", encoding="utf-8")

    try:
        with patch("app.services.preview_service.workspace_service") as mock_ws, patch(
            "app.services.preview_service.sandbox_service"
        ) as mock_sandbox:
            mock_ws.get_repo_path.return_value = tmp_path
            mock_ws.ensure_project_repo.return_value = _mock_repo("sha-1")
            mock_sandbox.start_background_service.return_value = {
                "container": MagicMock(),
                "host_port": 54321,
            }

            with patch.object(service, "_wait_until_ready", return_value=True):
                service.start_preview(feature_id)

            with pytest.raises(PreviewConflictError) as exc_info:
                service.start_preview(other_feature_id)

            assert exc_info.value.conflicting_feature_id == feature_id
    finally:
        store.database["features"].delete_one({"feature_id": other_feature_id})


def test_restarting_the_same_feature_is_allowed_not_a_conflict(service, feature_and_project, tmp_path):
    _project_id, feature_id = feature_and_project
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("abc123", encoding="utf-8")

    with patch("app.services.preview_service.workspace_service") as mock_ws, patch(
        "app.services.preview_service.sandbox_service"
    ) as mock_sandbox:
        mock_ws.get_repo_path.return_value = tmp_path
        mock_ws.ensure_project_repo.return_value = _mock_repo("sha-1")
        first_container = MagicMock()
        mock_sandbox.start_background_service.return_value = {
            "container": first_container,
            "host_port": 11111,
        }

        with patch.object(service, "_wait_until_ready", return_value=True):
            service.start_preview(feature_id)

            mock_sandbox.start_background_service.return_value = {
                "container": MagicMock(),
                "host_port": 22222,
            }
            result = service.start_preview(feature_id)

        # The first container was stopped before the second one started.
        mock_sandbox.stop_background_service.assert_any_call(first_container)

    assert result["preview_url"] == "http://localhost:22222"


def test_stop_is_idempotent_on_a_feature_with_no_session(service, feature_and_project):
    _project_id, feature_id = feature_and_project
    service.stop_preview(feature_id)  # must not raise


def test_stop_removes_the_session_and_stops_the_container(service, feature_and_project, tmp_path):
    _project_id, feature_id = feature_and_project
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("abc123", encoding="utf-8")

    with patch("app.services.preview_service.workspace_service") as mock_ws, patch(
        "app.services.preview_service.sandbox_service"
    ) as mock_sandbox:
        mock_ws.get_repo_path.return_value = tmp_path
        mock_ws.ensure_project_repo.return_value = _mock_repo("sha-1")
        container = MagicMock()
        mock_sandbox.start_background_service.return_value = {"container": container, "host_port": 33333}

        with patch.object(service, "_wait_until_ready", return_value=True):
            service.start_preview(feature_id)

        service.stop_preview(feature_id)
        mock_sandbox.stop_background_service.assert_called_with(container)

    assert service.get_status(feature_id) == {"status": "stopped", "preview_url": None, "started_at": None}


def test_find_running_feature_for_project_returns_none_when_nothing_running(service, feature_and_project):
    project_id, _feature_id = feature_and_project
    assert service.find_running_feature_for_project(project_id) is None


def test_find_running_feature_for_project_finds_the_one_running_feature(service, feature_and_project, tmp_path):
    project_id, feature_id = feature_and_project
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("abc123", encoding="utf-8")

    with patch("app.services.preview_service.workspace_service") as mock_ws, patch(
        "app.services.preview_service.sandbox_service"
    ) as mock_sandbox:
        mock_ws.get_repo_path.return_value = tmp_path
        mock_ws.ensure_project_repo.return_value = _mock_repo("sha-1")
        mock_sandbox.start_background_service.return_value = {"container": MagicMock(), "host_port": 44444}

        with patch.object(service, "_wait_until_ready", return_value=True):
            service.start_preview(feature_id)

        assert service.find_running_feature_for_project(project_id) == feature_id
        assert service.find_running_feature_for_project("proj_does_not_exist") is None


def test_restart_if_running_is_a_noop_when_stopped(service, feature_and_project):
    _project_id, feature_id = feature_and_project
    assert service.restart_if_running(feature_id) is False


def test_restart_if_running_restarts_when_running(service, feature_and_project, tmp_path):
    _project_id, feature_id = feature_and_project
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "BUILD_ID").write_text("abc123", encoding="utf-8")

    with patch("app.services.preview_service.workspace_service") as mock_ws, patch(
        "app.services.preview_service.sandbox_service"
    ) as mock_sandbox:
        mock_ws.get_repo_path.return_value = tmp_path
        mock_ws.ensure_project_repo.return_value = _mock_repo("sha-1")
        first_container = MagicMock()
        mock_sandbox.start_background_service.return_value = {"container": first_container, "host_port": 11111}

        with patch.object(service, "_wait_until_ready", return_value=True):
            service.start_preview(feature_id)

            mock_sandbox.start_background_service.return_value = {"container": MagicMock(), "host_port": 22222}
            restarted = service.restart_if_running(feature_id)

        mock_sandbox.stop_background_service.assert_any_call(first_container)

    assert restarted is True
    assert service.get_status(feature_id)["preview_url"] == "http://localhost:22222"


def test_sweep_orphaned_containers_delegates_to_sandbox_service(service):
    with patch("app.services.preview_service.sandbox_service") as mock_sandbox:
        mock_sandbox.find_containers_by_label.return_value = [MagicMock(), MagicMock()]

        stopped_count = service.sweep_orphaned_containers()

    assert stopped_count == 2
    assert mock_sandbox.stop_background_service.call_count == 2
