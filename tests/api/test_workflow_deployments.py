"""Tests for WorkflowDeployment CRUD endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.files.models import File
from api.platforms.models import Platform
from api.workflow.models import (
    Workflow, WorkflowVersion, WorkflowVersionAttribute,
)
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
    wf_id, _, ver_num = _create_workflow_and_version(session)

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
    wf_id, _, ver_num = _create_workflow_and_version(session)

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
    wf_id, _, ver_num = _create_workflow_and_version(session)

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
    wf_id, _, ver_num = _create_workflow_and_version(session)
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
    wf_id, _, ver_num = _create_workflow_and_version(session)

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
    wf_id, _, ver_num = _create_workflow_and_version(session)

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
    wf_id, _, ver_num = _create_workflow_and_version(session)
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
    wf_id, _, ver_num = _create_workflow_and_version(session)

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
    wf_id, _, ver_num = _create_workflow_and_version(session)

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
    wf_id, _, ver_num = _create_workflow_and_version(session)

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
    """Set OMICS_REGISTER_WORKFLOW_LAMBDA env + clear settings cache.

    Also pins ENVIRONMENT=dev so tests asserting on the ngs360_env tag
    don't depend on whatever the host shell / CI runner has set.
    """
    monkeypatch.setenv(
        "OMICS_REGISTER_WORKFLOW_LAMBDA", "test-omics-register-lambda",
    )
    monkeypatch.setenv("ENVIRONMENT", "dev")
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
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    arn = f"{OMICS_ARN_PREFIX}workflow/1324105/version/{ver_num}"
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
    assert inv["Payload"]["id"] == wf_id


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
    v1_arn = f"{OMICS_ARN_PREFIX}workflow/9999999/version/1"
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


# ---------------------------------------------------------------------------
# Omics tag propagation from WorkflowVersion.attributes
# ---------------------------------------------------------------------------

def _attach_attributes(
    session: Session, version_id: str, pairs: list[tuple[str, str]],
) -> None:
    """Insert WorkflowVersionAttribute rows for a version. Kept inline
    to avoid coupling test setup to the API's create endpoint.

    Converts ``version_id`` (returned as str by the create helpers) to a
    UUID object because SQLAlchemy's UUID column processor calls
    ``value.hex`` and strings don't have that attribute.
    """
    ver_uuid = uuid.UUID(version_id) if isinstance(version_id, str) else version_id
    for key, value in pairs:
        session.add(WorkflowVersionAttribute(
            workflow_version_id=ver_uuid, key=key, value=value,
        ))
    session.commit()


def test_omics_deployment_forwards_git_attributes_as_tags(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Version attributes in the allowlist ride along on the lambda payload
    so Omics tags a workflow with its git provenance at register time."""
    _seed_omics_platform(session)
    wf_id, ver_id, ver_num = _create_cwl_workflow_and_version(session)
    _attach_attributes(session, ver_id, [
        ("git_commit", "aabbccddeeff00112233445566778899aabbccdd"),
        ("git_repo", "https://github.com/example-org/example-repo"),
        ("git_ref", "main"),
    ])

    arn = f"{OMICS_ARN_PREFIX}workflow/1324105/version/{ver_num}"
    mock_lambda_client.set_response({
        "statusCode": 200, "workflow_id": "1324105", "arn": arn,
    })

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201, resp.text

    inv = mock_lambda_client.invocations[-1]
    assert inv["Payload"]["action"] == "create_workflow"
    assert inv["Payload"]["tags"] == {
        "git_commit": "aabbccddeeff00112233445566778899aabbccdd",
        "git_repo": "https://github.com/example-org/example-repo",
        "git_ref": "main",
        "ngs360_env": "dev",
    }


def test_omics_deployment_version_forwards_git_attributes_as_tags(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """create_workflow_version branch also carries the git tags — pin
    the other injection site so a future refactor can't drop it silently."""
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
    session.refresh(v2)
    wf_id = str(wf.id)
    _attach_attributes(session, str(v2.id), [
        ("git_commit", "cafebabe1234567890abcdef1234567890abcdef"),
        ("git_ref", "main"),
    ])

    # Seed an existing Omics deployment on v1 (bypasses the lambda)
    v1_arn = f"{OMICS_ARN_PREFIX}workflow/9999999/version/1"
    client.post(
        f"/api/v1/workflows/{wf_id}/versions/1/deployments",
        json={"engine": OMICS_ENGINE, "external_id": v1_arn},
    )

    mock_lambda_client.set_response({
        "statusCode": 200, "version_name": "2",
        "omics_workflow_id": "9999999",
        "arn": f"{OMICS_ARN_PREFIX}workflow/9999999/version/2",
    })
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/2/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201, resp.text

    inv = mock_lambda_client.invocations[-1]
    assert inv["Payload"]["action"] == "create_workflow_version"
    assert inv["Payload"]["tags"] == {
        "git_commit": "cafebabe1234567890abcdef1234567890abcdef",
        "git_ref": "main",
        "ngs360_env": "dev",
    }


def test_omics_deployment_filters_non_allowlisted_attributes(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Attributes outside the git_* allowlist stay in NGS360's DB and
    do not surface on Omics — the allowlist is the security boundary."""
    _seed_omics_platform(session)
    wf_id, ver_id, ver_num = _create_cwl_workflow_and_version(session)
    _attach_attributes(session, ver_id, [
        ("git_commit", "abc1234"),
        ("foo", "bar"),                    # not allowlisted
        ("internal_note", "sensitive"),    # not allowlisted
    ])

    mock_lambda_client.set_response({
        "statusCode": 200, "workflow_id": "1",
        "arn": f"{OMICS_ARN_PREFIX}workflow/1/version/{ver_num}",
    })
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201, resp.text

    inv = mock_lambda_client.invocations[-1]
    assert inv["Payload"]["tags"] == {"git_commit": "abc1234", "ngs360_env": "dev"}


def test_omics_deployment_tags_carry_only_env_when_no_attributes(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """A version with no attributes still gets the ngs360_env deployment
    tag — it's set unconditionally at payload-construction time. Pins
    that the tags dict is always non-empty (lambda always has at least
    one caller-supplied tag to merge with NGS360_workflow_id)."""
    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    mock_lambda_client.set_response({
        "statusCode": 200, "workflow_id": "1",
        "arn": f"{OMICS_ARN_PREFIX}workflow/1/version/{ver_num}",
    })
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201, resp.text

    inv = mock_lambda_client.invocations[-1]
    assert inv["Payload"]["tags"] == {"ngs360_env": "dev"}


def test_omics_deployment_ngs360_env_reflects_environment_setting(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env, monkeypatch,
):
    """The ngs360_env tag value comes from settings.ENVIRONMENT — a
    staging APIServer stamps `ngs360_env: staging` on the workflow it
    registers, so provenance of "which tier created this Omics resource"
    is queryable directly from the Omics tags."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    get_settings.cache_clear()

    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    mock_lambda_client.set_response({
        "statusCode": 200, "workflow_id": "1",
        "arn": f"{OMICS_ARN_PREFIX}workflow/1/version/{ver_num}",
    })
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201, resp.text

    inv = mock_lambda_client.invocations[-1]
    assert inv["Payload"]["tags"]["ngs360_env"] == "staging"


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


def test_omics_lambda_client_configured_for_slow_registrations(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """The Lambda client must outwait the registration and never retry it.

    botocore's defaults are both wrong here: a 60s read_timeout is shorter
    than a real registration, and the default retry policy treats the
    resulting ReadTimeoutError as retryable -- re-invoking a non-idempotent
    Omics registration up to five times.
    """
    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    mock_lambda_client.set_response({
        "statusCode": 200,
        "arn": f"{OMICS_ARN_PREFIX}workflow/4256500",
    })

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201

    config = mock_lambda_client.client_kwargs["config"]
    assert config.read_timeout == 300
    assert config.retries["max_attempts"] == 1


def test_omics_lambda_read_timeout_setting_is_honoured(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env, monkeypatch,
):
    """OMICS_REGISTER_LAMBDA_READ_TIMEOUT overrides the default."""
    monkeypatch.setenv("OMICS_REGISTER_LAMBDA_READ_TIMEOUT", "450")
    get_settings.cache_clear()

    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    mock_lambda_client.set_response({
        "statusCode": 200,
        "arn": f"{OMICS_ARN_PREFIX}workflow/4256500",
    })

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201
    assert mock_lambda_client.client_kwargs["config"].read_timeout == 450


def test_omics_deployment_lambda_read_timeout_returns_504(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """A timed-out invoke returns 504 with reconciliation guidance.

    It used to escape as an unhandled 500, which said nothing about the fact
    that the registration had very likely completed on AWS -- so the operator
    could not tell this apart from a deploy that never happened.
    """
    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    mock_lambda_client.simulate_error("ReadTimeoutError")

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 504
    detail = resp.json()["detail"]
    assert "may still have completed" in detail
    assert "external_id" in detail

    # Exactly one invoke: the registration is not idempotent, so a retry
    # would attempt to create a workflow version that may already exist.
    assert len(mock_lambda_client.invocations) == 1

    # And no half-written deployment row.
    assert client.get(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
    ).json() == []


def test_omics_deployment_recoverable_after_timeout(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """After a timeout, the caller can record the ARN AWS already created.

    This is the repair path the 504's detail points at, and the reason the
    timeout must not leave a partial row behind: the retry has to be able to
    claim the (version, engine) pair.
    """
    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    mock_lambda_client.simulate_error("ReadTimeoutError")
    assert client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    ).status_code == 504

    # Operator finds the version on AWS and records it without redeploying.
    arn = f"{OMICS_ARN_PREFIX}workflow/4256500/version/{ver_num}"
    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE, "external_id": arn},
    )
    assert resp.status_code == 201
    assert resp.json()["external_id"] == arn
    # Still one invoke -- the repair does not touch the Lambda.
    assert len(mock_lambda_client.invocations) == 1


def test_omics_deployment_with_explicit_external_id_skips_lambda(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Caller-supplied external_id is stored as-is; Lambda is not invoked."""
    _seed_omics_platform(session)
    wf_id, _, ver_num = _create_cwl_workflow_and_version(session)

    arn = f"{OMICS_ARN_PREFIX}workflow/4256500/version/{ver_num}"
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


# ---------------------------------------------------------------------------
# ngs360:// definition URI resolution for Omics deployments
# ---------------------------------------------------------------------------

def _create_ngs360_cwl_workflow_and_version(
    session: Session,
    definition_uri: str,
) -> tuple[str, str, int]:
    """Insert a workflow + version with an arbitrary definition_uri."""
    wf = Workflow(name="NGS360 CWL", created_by="testuser")
    session.add(wf)
    session.flush()
    ver = WorkflowVersion(
        workflow_id=wf.id,
        version=1,
        definition_uri=definition_uri,
        created_by="testuser",
    )
    session.add(ver)
    session.commit()
    session.refresh(wf)
    session.refresh(ver)
    return str(wf.id), str(ver.id), ver.version


def test_omics_deployment_resolves_ngs360_definition_uri(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """ngs360://<file-id> is resolved to the file's s3:// uri before Lambda."""
    _seed_omics_platform(session)

    # Seed a File record that stands in for the NGS360 upload
    file_record = File(
        uri="s3://example-bucket/workflows/workflow.cwl",
        original_filename="workflow.cwl",
        created_by="testuser",
        storage_backend="s3",
    )
    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    wf_id, _, ver_num = _create_ngs360_cwl_workflow_and_version(
        session, definition_uri=f"ngs360://{file_record.id}",
    )

    arn = f"{OMICS_ARN_PREFIX}workflow/1324105/version/{ver_num}"
    mock_lambda_client.set_response({
        "statusCode": 200,
        "workflow_id": "1324105",
        "arn": arn,
    })

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 201, resp.text

    inv = mock_lambda_client.invocations[-1]
    assert inv["Payload"]["cwl_s3_path"] == file_record.uri


def test_omics_deployment_ngs360_file_not_found_returns_404(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Unknown ngs360 file id yields 404 and no Lambda invocation."""
    _seed_omics_platform(session)

    missing_id = "00000000-0000-0000-0000-000000000000"
    wf_id, _, ver_num = _create_ngs360_cwl_workflow_and_version(
        session, definition_uri=f"ngs360://{missing_id}",
    )

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 404
    assert mock_lambda_client.invocations == []


def test_omics_deployment_ngs360_invalid_uuid_returns_400(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Malformed ngs360:// id (not a UUID) yields 400."""
    _seed_omics_platform(session)

    wf_id, _, ver_num = _create_ngs360_cwl_workflow_and_version(
        session, definition_uri="ngs360://not-a-uuid",
    )

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 400
    assert mock_lambda_client.invocations == []


def test_omics_deployment_ngs360_non_s3_backing_returns_400(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """A local-backed NGS360 file cannot back an Omics deployment."""
    _seed_omics_platform(session)

    file_record = File(
        uri="local/path/workflow.cwl",
        original_filename="workflow.cwl",
        created_by="testuser",
        storage_backend="local",
    )
    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    wf_id, _, ver_num = _create_ngs360_cwl_workflow_and_version(
        session, definition_uri=f"ngs360://{file_record.id}",
    )

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 400
    assert mock_lambda_client.invocations == []


def test_omics_deployment_unsupported_scheme_returns_400(
    client: TestClient, session: Session,
    mock_lambda_client, omics_env,
):
    """Non-s3, non-ngs360 definition_uri is rejected before Lambda."""
    _seed_omics_platform(session)

    wf_id, _, ver_num = _create_ngs360_cwl_workflow_and_version(
        session, definition_uri="https://example.com/wf.cwl",
    )

    resp = client.post(
        f"/api/v1/workflows/{wf_id}/versions/{ver_num}/deployments",
        json={"engine": OMICS_ENGINE},
    )
    assert resp.status_code == 400
    assert mock_lambda_client.invocations == []
