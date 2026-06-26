"""Tests for WorkflowDeployment CRUD endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.platforms.models import Platform
from api.workflow.models import Workflow, WorkflowVersion
from core.config import get_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_workflow_and_version(
    session: Session,
) -> tuple[str, str, int]:
    """Insert a workflow + version; return (wf_id, version_uuid, version_num)."""
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
    return str(wf.id), str(ver.id), ver.version


def _seed_platforms(session: Session) -> None:
    """Ensure Arvados and SevenBridges platforms exist."""
    for name in ["Arvados", "SevenBridges"]:
        session.add(Platform(name=name))
    session.commit()


# ---------------------------------------------------------------------------
# POST /workflows/{id}/versions/{version_num}/deployments
# ---------------------------------------------------------------------------

def test_create_deployment(
    client: TestClient, session: Session,
):
    """Deploy a workflow version on a platform engine."""
    _seed_platforms(session)
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    body = {
        "engine": "Arvados",
        "external_id": "arvados-wf-abc123",
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
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
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    body = {
        "engine": "SevenBridges",
        "external_id": "sb-app-xyz",
    }
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json=body,
    )
    assert resp.status_code == 201
    assert resp.json()["external_id"] == "sb-app-xyz"


def test_create_deployment_duplicate_engine_conflict(
    client: TestClient, session: Session,
):
    """Duplicate (version_num, engine) pair returns 409."""
    _seed_platforms(session)
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    body = {"engine": "Arvados", "external_id": "arv-1"}
    resp1 = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json=body,
    )
    assert resp1.status_code == 201

    body2 = {"engine": "Arvados", "external_id": "arv-2"}
    resp2 = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
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

    body = {"engine": "Arvados", "external_id": "x"}
    resp = client.post(
        f"/api/v1/workflows/{wf.id}/versions/99"
        f"/deployments",
        json=body,
    )
    assert resp.status_code == 404


def test_create_deployment_invalid_engine(
    client: TestClient, session: Session,
):
    """Deployment with an unregistered engine returns 400."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    body = {"engine": "UnknownPlatform", "external_id": "x"}
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json=body,
    )
    assert resp.status_code == 400
    assert "not a registered platform" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /workflows/{id}/versions/{version_num}/deployments
# ---------------------------------------------------------------------------

def test_get_deployments_empty(
    client: TestClient, session: Session,
):
    """List deployments for a version with none."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)
    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_deployments_multiple(
    client: TestClient, session: Session,
):
    """List deployments after adding two engines."""
    _seed_platforms(session)
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json={
            "engine": "SevenBridges",
            "external_id": "sb-1",
        },
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
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
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    create_resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    dep_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments/{dep_id}",
    )
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
    )
    assert list_resp.json() == []


def test_delete_deployment_not_found(
    client: TestClient, session: Session,
):
    """Deleting a non-existent deployment returns 404."""
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)
    fake_dep = "00000000-0000-0000-0000-000000000000"

    resp = client.delete(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments/{fake_dep}",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET .../versions/{version_num}/deployments?engine=
# ---------------------------------------------------------------------------

def test_get_deployments_filter_by_engine(
    client: TestClient, session: Session,
):
    """Filter version-level deployments by engine."""
    _seed_platforms(session)
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json={
            "engine": "SevenBridges",
            "external_id": "sb-1",
        },
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
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
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
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
    wf_id, ver_id, ver_num = _create_workflow_and_version(session)

    client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-1"},
    )

    resp = client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}",
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
) -> tuple[str, int, int]:
    """Seed workflow with 2 versions, each deployed on Arvados.

    Also deploys v1 on SevenBridges.
    Returns (wf_id, v1_num, v2_num).
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
    wf_id = str(wf.id)

    # v1: Arvados + SevenBridges
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/1"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-v1"},
    )
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/1"
        f"/deployments",
        json={
            "engine": "SevenBridges",
            "external_id": "sb-v1",
        },
    )
    # v2: Arvados only
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/2"
        f"/deployments",
        json={"engine": "Arvados", "external_id": "arv-v2"},
    )
    return wf_id, 1, 2


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
    wf_id, v1_num, _ = _create_two_versions_with_deps(
        client, session,
    )
    # Set production → v1
    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": v1_num},
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
    wf_id, v1_num, _ = _create_two_versions_with_deps(
        client, session,
    )
    client.put(
        f"/api/v1/workflows/{wf_id}/aliases/production",
        json={"version_num": v1_num},
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


# ---------------------------------------------------------------------------
# Omics auto-register flow
# ---------------------------------------------------------------------------

OMICS_ENGINE = "AWSHealthOmics (us-east)"
OMICS_ARN_PREFIX = "arn:aws:omics:us-east-1:123456789012:"


@pytest.fixture(name="omics_env")
def omics_env_fixture(monkeypatch):
    """Set OMICS_REGISTER_WORKFLOW_LAMBDA env + clear settings cache."""
    monkeypatch.setenv(
        "OMICS_REGISTER_WORKFLOW_LAMBDA", "test-omics-register-lambda",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_omics_platform(session: Session) -> None:
    session.add(Platform(name=OMICS_ENGINE))
    session.commit()


def _create_cwl_workflow_and_version(
    session: Session,
) -> tuple[str, str, int]:
    """Insert a workflow + CWL version; return (wf_id, version_uuid, version_num)."""
    wf = Workflow(
        name="CWL Alignment",
        created_by="testuser",
    )
    session.add(wf)
    session.flush()
    ver = WorkflowVersion(
        workflow_id=wf.id,
        version=1,
        definition_uri="s3://bucket/align.cwl",
        created_by="testuser",
    )
    session.add(ver)
    session.commit()
    session.refresh(wf)
    session.refresh(ver)
    return str(wf.id), str(ver.id), ver.version


def test_omics_deployment_first_version_registers_via_lambda(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """First Omics deployment of a workflow uses action=create_workflow."""
    _seed_omics_platform(session)
    wf_id, ver_id, ver_num = _create_cwl_workflow_and_version(session)

    arn = f"{OMICS_ARN_PREFIX}workflow/1324105/version/{ver_id}"
    mock_lambda_client.set_response({
        "statusCode": 200,
        "workflow_id": "1324105",
        "arn": arn,
        "message": "Registered",
    })

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["engine"] == OMICS_ENGINE
    assert data["external_id"] == arn

    # Lambda was invoked with create_workflow action
    assert len(mock_lambda_client.invocations) == 1
    inv = mock_lambda_client.invocations[0]
    assert inv["FunctionName"] == "test-omics-register-lambda"
    assert inv["Payload"]["action"] == "create_workflow"
    assert inv["Payload"]["source"] == "ngs360"
    assert inv["Payload"]["name"] == "CWL Alignment"
    assert inv["Payload"]["cwl_s3_path"] == "s3://bucket/align.cwl"
    assert inv["Payload"]["id"] == ver_id


def test_omics_deployment_second_version_uses_create_version(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """A Workflow that already has an Omics deployment uses create_workflow_version."""
    _seed_omics_platform(session)

    wf = Workflow(name="Multi", created_by="testuser")
    session.add(wf)
    session.flush()
    v1 = WorkflowVersion(
        workflow_id=wf.id, version=1,
        definition_uri="s3://b/v1.cwl", created_by="testuser",
    )
    v2 = WorkflowVersion(
        workflow_id=wf.id, version=2,
        definition_uri="s3://b/v2.cwl", created_by="testuser",
    )
    session.add_all([v1, v2])
    session.commit()
    session.refresh(wf)
    session.refresh(v1)
    session.refresh(v2)
    wf_id = str(wf.id)

    # Seed an existing Omics deployment on v1 (caller-supplied external_id path)
    v1_arn = f"{OMICS_ARN_PREFIX}workflow/9999999/version/{v1.id}"
    resp1 = client.post(
        f"/api/v1/workflows/{wf_id}/versions/1/deployments",
        json={"engine": OMICS_ENGINE, "external_id": v1_arn},
    )
    assert resp1.status_code == 201, resp1.text
    assert mock_lambda_client.invocations == []  # caller supplied → no Lambda

    # Now deploy v2 without external_id → Lambda is invoked, action=create_workflow_version
    v2_arn = f"{OMICS_ARN_PREFIX}workflow/9999999/version/2"
    mock_lambda_client.set_response({
        "statusCode": 200,
        "version_name": "2",
        "omics_workflow_id": "9999999",
        "arn": v2_arn,
    })
    resp2 = client.post(
        f"/api/v1/workflows/{wf_id}/versions/2/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp2.status_code == 201, resp2.text

    inv = mock_lambda_client.invocations[-1]
    assert inv["Payload"]["action"] == "create_workflow_version"
    assert inv["Payload"]["omics_workflow_id"] == "9999999"
    assert inv["Payload"]["version_name"] == "2"
    assert inv["Payload"]["cwl_s3_path"] == "s3://b/v2.cwl"


def test_omics_deployment_lambda_not_configured(
    client: TestClient, session: Session, monkeypatch,
):
    """Without OMICS_REGISTER_WORKFLOW_LAMBDA set, Omics auto-register fails 500."""
    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    monkeypatch.delenv("OMICS_REGISTER_WORKFLOW_LAMBDA", raising=False)
    get_settings.cache_clear()

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 500
    assert "OMICS_REGISTER_WORKFLOW_LAMBDA" in resp.json()["detail"]


def test_omics_deployment_lambda_returns_error_status(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Lambda error statusCode propagates as 502."""
    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    mock_lambda_client.set_response({
        "statusCode": 500,
        "error": "WorkflowRegistrationError",
        "message": "ECR auth failed",
    })

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 502
    assert "ECR auth failed" in resp.json()["detail"]


def test_omics_deployment_lambda_missing_arn(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Lambda success but no arn field returns 502."""
    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    mock_lambda_client.set_response({
        "statusCode": 200,
        "workflow_id": "1324105",
    })

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 502
    assert "arn" in resp.json()["detail"]


def test_omics_deployment_with_explicit_external_id_skips_lambda(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Caller-supplied external_id is stored as-is; Lambda is not invoked."""
    _seed_omics_platform(session)
    wf_id, ver_id, ver_num = _create_cwl_workflow_and_version(session)

    arn = f"{OMICS_ARN_PREFIX}workflow/4256500/version/{ver_id}"
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE, "external_id": arn},
    )
    assert resp.status_code == 201
    assert resp.json()["external_id"] == arn
    assert mock_lambda_client.invocations == []


def test_non_omics_deployment_without_external_id_400(
    client: TestClient, session: Session,
):
    """Non-Omics engine without external_id is rejected 400."""
    _seed_platforms(session)
    wf_id, _, ver_num = _create_workflow_and_version(session)

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": "Arvados"},
    )
    assert resp.status_code == 400
    assert "external_id is required" in resp.json()["detail"]
