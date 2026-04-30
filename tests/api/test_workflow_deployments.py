"""Tests for WorkflowDeployment CRUD endpoints."""

from fastapi.testclient import TestClient
from sqlmodel import Session

from api.platforms.models import Platform
from api.workflow.models import Workflow, WorkflowVersion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_workflow_and_version(
    session: Session,
) -> tuple[str, str]:
    """Insert a workflow + version; return (wf_id, version_id)."""
    wf = Workflow(
        name="WDL Alignment",
        created_by="testuser",
    )
    session.add(wf)
    session.flush()
    ver = WorkflowVersion(
        workflow_id=wf.id,
        version=1,
        definition_uri="s3://bucket/align.wdl",
        created_by="testuser",
    )
    session.add(ver)
    session.commit()
    session.refresh(wf)
    session.refresh(ver)
    return str(wf.id), str(ver.id)


def _seed_platforms(session: Session) -> None:
    """Ensure Arvados and SevenBridges platforms exist."""
    for name in ["Arvados", "SevenBridges"]:
        session.add(Platform(name=name))
    session.commit()


# ---------------------------------------------------------------------------
# POST /workflows/{id}/versions/{vid}/deployments
# ---------------------------------------------------------------------------

def test_create_deployment(
    client: TestClient, session: Session,
):
    """Deploy a workflow version on a platform engine."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {
        "engine": "Arvados",
        "external_id": "arvados-wf-abc123",
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json=body,
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["workflow_version_id"] == ver_id
    assert data["engine"] == "Arvados"
    assert data["external_id"] == "arvados-wf-abc123"
    assert data["created_by"] == "testuser"
    assert "id" in data
    assert "created_at" in data


def test_create_deployment_minimal(
    client: TestClient, session: Session,
):
    """Only engine and external_id are required."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {
        "engine": "SevenBridges",
        "external_id": "sb-app-xyz",
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json=body,
    )
    assert resp.status_code == 201
    assert resp.json()["external_id"] == "sb-app-xyz"


def test_create_deployment_duplicate_engine_conflict(
    client: TestClient, session: Session,
):
    """Duplicate (version_id, engine) pair returns 409."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {"engine": "Arvados", "external_id": "arv-1"}
    resp1 = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json=body,
    )
    assert resp1.status_code == 201

    body2 = {"engine": "Arvados", "external_id": "arv-2"}
    resp2 = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json=body2,
    )
    assert resp2.status_code == 409


def test_create_deployment_version_not_found(
    client: TestClient, session: Session,
):
    """Deployment on a non-existent version returns 404."""
    _seed_platforms(session)
    wf = Workflow(name="WF", created_by="testuser")
    session.add(wf)
    session.commit()
    session.refresh(wf)

    fake_ver = "00000000-0000-0000-0000-000000000000"
    body = {"engine": "Arvados", "external_id": "x"}
    resp = client.post(
        f"/api/v1/workflows/{wf.id}/versions/{fake_ver}"
        f"/deployments",
        json=body,
    )
    assert resp.status_code == 404


def test_create_deployment_invalid_engine(
    client: TestClient, session: Session,
):
    """Deployment with an unregistered engine returns 400."""
    wf_id, ver_id = _create_workflow_and_version(session)

    body = {"engine": "UnknownPlatform", "external_id": "x"}
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json=body,
    )
    assert resp.status_code == 400
    assert "not a registered platform" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /workflows/{id}/versions/{vid}/deployments
# ---------------------------------------------------------------------------

def test_get_deployments_empty(
    client: TestClient, session: Session,
):
    """List deployments for a version with none."""
    wf_id, ver_id = _create_workflow_and_version(session)
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_deployments_multiple(
    client: TestClient, session: Session,
):
    """List deployments after adding two engines."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json={
            "engine": "SevenBridges",
            "external_id": "sb-1",
        },
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    engines = {r["engine"] for r in data}
    assert engines == {"Arvados", "SevenBridges"}


# ---------------------------------------------------------------------------
# DELETE .../deployments/{deployment_id}
# ---------------------------------------------------------------------------

def test_delete_deployment(
    client: TestClient, session: Session,
):
    """Delete a deployment returns 204 and it's gone."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    create_resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    dep_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments/{dep_id}",
    )
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
    )
    assert list_resp.json() == []


def test_delete_deployment_not_found(
    client: TestClient, session: Session,
):
    """Deleting a non-existent deployment returns 404."""
    wf_id, ver_id = _create_workflow_and_version(session)
    fake_dep = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments/{fake_dep}",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET .../versions/{vid}/deployments?engine=
# ---------------------------------------------------------------------------

def test_get_deployments_filter_by_engine(
    client: TestClient, session: Session,
):
    """Filter version-level deployments by engine."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json={
            "engine": "SevenBridges",
            "external_id": "sb-1",
        },
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments?engine=Arvados",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["engine"] == "Arvados"


def test_get_deployments_filter_engine_no_match(
    client: TestClient, session: Session,
):
    """Engine filter returns empty list when no match."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments?engine=SevenBridges",
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Version GET includes deployments
# ---------------------------------------------------------------------------

def test_version_public_includes_deployments(
    client: TestClient, session: Session,
):
    """GET version includes nested deployment data."""
    _seed_platforms(session)
    wf_id, ver_id = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_id}",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["deployments"]) == 1
    assert data["deployments"][0]["engine"] == "Arvados"


# ---------------------------------------------------------------------------
# GET /workflows/{id}/deployments  (workflow-level, with filters)
# ---------------------------------------------------------------------------

def _create_two_versions_with_deps(
    client: TestClient, session: Session,
) -> tuple[str, str, str]:
    """Seed workflow with 2 versions, each deployed on Arvados.

    Also deploys v1 on SevenBridges.
    Returns (wf_id, v1_id, v2_id).
    """
    _seed_platforms(session)
    wf = Workflow(name="Multi-Ver WF", created_by="testuser")
    session.add(wf)
    session.flush()
    v1 = WorkflowVersion(
        workflow_id=wf.id, version=1,
        definition_uri="s3://b/v1.wdl", created_by="testuser",
    )
    v2 = WorkflowVersion(
        workflow_id=wf.id, version=2,
        definition_uri="s3://b/v2.wdl", created_by="testuser",
    )
    session.add_all([v1, v2])
    session.commit()
    session.refresh(wf)
    session.refresh(v1)
    session.refresh(v2)
    wf_id, v1_id, v2_id = str(wf.id), str(v1.id), str(v2.id)

    # v1: Arvados + SevenBridges
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{v1_id}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-v1"},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{v1_id}"
        f"/deployments",
        json={
            "engine": "SevenBridges",
            "external_id": "sb-v1",
        },
    )
    # v2: Arvados only
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{v2_id}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-v2"},
    )
    return wf_id, v1_id, v2_id


def test_workflow_deployments_no_filter(
    client: TestClient, session: Session,
):
    """No filters returns all deployments across all versions."""
    wf_id, _, _ = _create_two_versions_with_deps(
        client, session,
    )
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/deployments",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3  # arv-v1, sb-v1, arv-v2


def test_workflow_deployments_filter_engine(
    client: TestClient, session: Session,
):
    """Engine filter returns only matching engine across versions."""
    wf_id, _, _ = _create_two_versions_with_deps(
        client, session,
    )
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/deployments"
        f"?engine=Arvados",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(r["engine"] == "Arvados" for r in data)


def test_workflow_deployments_filter_alias(
    client: TestClient, session: Session,
):
    """Alias filter resolves to a version and returns its deps."""
    wf_id, v1_id, _ = _create_two_versions_with_deps(
        client, session,
    )
    # Set production → v1
    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"workflow_version_id": v1_id},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/deployments"
        f"?alias=production",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2  # arv-v1 + sb-v1
    ext_ids = {r["external_id"] for r in data}
    assert ext_ids == {"arv-v1", "sb-v1"}


def test_workflow_deployments_filter_alias_and_engine(
    client: TestClient, session: Session,
):
    """Alias + engine yields at most one deployment."""
    wf_id, v1_id, _ = _create_two_versions_with_deps(
        client, session,
    )
    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"workflow_version_id": v1_id},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/deployments"
        f"?alias=production&engine=Arvados",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["external_id"] == "arv-v1"
    assert data[0]["engine"] == "Arvados"


def test_workflow_deployments_alias_not_set_404(
    client: TestClient, session: Session,
):
    """Alias that isn't set returns 404."""
    wf_id, _, _ = _create_two_versions_with_deps(
        client, session,
    )
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/deployments"
        f"?alias=production",
    )
    assert resp.status_code == 404
    assert "not set" in resp.json()["detail"]


def test_workflow_deployments_no_versions_empty(
    client: TestClient, session: Session,
):
    """Workflow with no versions returns empty list."""
    wf = Workflow(name="Empty WF", created_by="testuser")
    session.add(wf)
    session.commit()
    session.refresh(wf)

    resp = client.get(
        f"/api/v1/workflows/{wf.id}/deployments",
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_workflow_deployments_engine_no_match_empty(
    client: TestClient, session: Session,
):
    """Engine filter with no matching deployments returns []."""
    wf_id, _, _ = _create_two_versions_with_deps(
        client, session,
    )
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/deployments"
        f"?engine=NonExistent",
    )
    assert resp.status_code == 200
    assert resp.json() == []
