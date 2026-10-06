"""
Unit tests confirming Feature.updated_at is now a real "last activity" signal (previously dead
data, set once at creation and never bumped again -- see stage_event_service.record()/
approval_service.py's own new updated_at writes). Powers "open a project -> default to whichever
feature was most recently worked on" (ProjectWorkspacePage.jsx). Real Mongo-backed `store`
seeding (established convention, see test_approval_srs_exclusivity.py), no LLM/graph.
"""

import json
from datetime import datetime, timedelta

import pytest

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.schemas.approval_schema import ApprovalRequest
from app.services.approval_service import approval_service
from app.services.stage_event_service import stage_event_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


def _seed_artifact(tmp_path, project_id, feature_id, *, approval_status):
    artifact_id = generate_id("artifact")
    file_path = tmp_path / f"{artifact_id}.json"
    file_path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.CODER.value,
        "artifact_type": ArtifactType.CODE_DIFF.value,
        "artifact_format": ArtifactFormat.JSON.value,
        "approval_status": approval_status,
        "file_path": str(file_path),
        "version": 1,
    }
    return artifact_id


@pytest.fixture
def stale_feature():
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    created_at = datetime.utcnow() - timedelta(days=3)

    store.projects[project_id] = {"project_id": project_id, "project_name": "P"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "F",
        "feature_description": "d",
        "created_at": created_at,
        "updated_at": created_at,
    }

    yield {"project_id": project_id, "feature_id": feature_id, "created_at": created_at}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    store.database["approvals"].delete_many({"feature_id": feature_id})
    store.database["stage_events"].delete_many({"feature_id": feature_id})


def test_stage_event_record_bumps_feature_updated_at(stale_feature):
    feature_id = stale_feature["feature_id"]
    created_at = stale_feature["created_at"]

    stage_event_service.record(
        feature_id=feature_id,
        agent_name=AgentName.CODER,
        event_type="run",
        human_comment=None,
    )

    assert store.features.get(feature_id)["updated_at"] > created_at


def test_stage_event_record_is_a_safe_no_op_for_an_unknown_feature():
    # Must never raise just because the feature lookup misses.
    result = stage_event_service.record(
        feature_id="feature_does_not_exist",
        agent_name=AgentName.REQUIREMENT,
        event_type="run",
        human_comment=None,
    )
    assert result is not None


def test_submit_approval_bumps_feature_updated_at(stale_feature, tmp_path):
    feature_id = stale_feature["feature_id"]
    project_id = stale_feature["project_id"]
    created_at = stale_feature["created_at"]
    artifact_id = _seed_artifact(tmp_path, project_id, feature_id, approval_status=ApprovalStatus.PENDING.value)

    approval_service.submit_approval(artifact_id, ApprovalRequest(status=ApprovalStatus.APPROVED))

    assert store.features.get(feature_id)["updated_at"] > created_at


def test_revoke_approval_bumps_feature_updated_at(stale_feature, tmp_path):
    feature_id = stale_feature["feature_id"]
    project_id = stale_feature["project_id"]
    artifact_id = _seed_artifact(tmp_path, project_id, feature_id, approval_status=ApprovalStatus.APPROVED.value)

    # Re-stamp updated_at to a stale value AFTER seeding (seeding itself didn't touch it), so the
    # revoke's own bump is the only thing that could move it forward.
    stale_again = datetime.utcnow() - timedelta(days=1)
    store.features[feature_id]["updated_at"] = stale_again

    approval_service.revoke_approval(artifact_id)

    assert store.features.get(feature_id)["updated_at"] > stale_again


def test_a_feature_with_more_recent_activity_is_the_one_a_project_would_default_to(tmp_path):
    """
    Direct end-to-end proof of the actual real-world scenario this exists for: two features in
    the same project, the OLDER one created first but the NEWER one (or rather, whichever one)
    genuinely worked on more recently -- confirms updated_at correctly reflects real activity
    order, not creation order, which is exactly what ProjectWorkspacePage.jsx's own
    `features.reduce(...)` picks the max of.
    """
    project_id = generate_id("project")
    older_feature_id = generate_id("feature")
    newer_feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P"}

    base = datetime.utcnow() - timedelta(days=5)
    store.features[older_feature_id] = {
        "project_id": project_id, "feature_id": older_feature_id, "feature_name": "Older",
        "feature_description": "d", "created_at": base, "updated_at": base,
    }
    store.features[newer_feature_id] = {
        "project_id": project_id, "feature_id": newer_feature_id, "feature_name": "Newer",
        "feature_description": "d", "created_at": base + timedelta(hours=1), "updated_at": base + timedelta(hours=1),
    }

    try:
        # Real, recent activity happens on the OLDER feature -- it should now be "more recently
        # active" than the newer-but-untouched-since-creation one.
        stage_event_service.record(
            feature_id=older_feature_id, agent_name=AgentName.CODER, event_type="run", human_comment=None,
        )

        older = store.features.get(older_feature_id)
        newer = store.features.get(newer_feature_id)
        assert older["updated_at"] > newer["updated_at"]
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_many({"project_id": project_id})
        store.database["stage_events"].delete_many({"feature_id": older_feature_id})
