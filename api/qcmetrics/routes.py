"""
Routes/endpoints for the QCMetrics API.

Provides endpoints for creating, searching, and deleting QC records.
"""

from typing import Optional
from fastapi import APIRouter, Query, status

from api.qcmetrics.models import (
    QCRecordCreate,
    QCRecordCreated,
    QCRecordPublic,
    QCRecordsPublic,
    QCRecordSearchRequest,
)
from api.qcmetrics import services
from api.auth.deps import CurrentActiveUser
from core.deps import SessionDep

router = APIRouter(prefix="/qcmetrics", tags=["QC Metrics"])


@router.post(
    "",
    response_model=QCRecordCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new QC record",
)
def create_qcrecord(
    session: SessionDep,
    current_user: CurrentActiveUser,
    qcrecord_create: QCRecordCreate,
) -> QCRecordCreated:
    """
    Create a new QC record with metrics and output files.

    The record stores quality control metrics from a pipeline execution.
    The `created_by` field is automatically set from the authenticated user.

    **Authentication required:** Bearer token must be provided.

    **Scoping:** Provide exactly one of `project_id` (project-scoped) or
    `sequencing_run_id` (run-scoped, e.g. demux stats).

    **Example — project-scoped:**

    ```bash
    curl -X POST "http://localhost:8000/api/v1/qcmetrics" \\
      -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \\
      -H "Content-Type: application/json" \\
      -d '{
        "project_id": "P-1234",
        "metadata": { "pipeline": "RNA-Seq", "version": "2.0.0" },
        "metrics": [{
          "name": "alignment_stats",
          "samples": [{"sample_name": "Sample1"}],
          "values": {"reads": 50000000, "alignment_rate": 95.5}
        }]
      }'
    ```

    **Example — run-scoped (demux stats):**

    ```bash
    curl -X POST "http://localhost:8000/api/v1/qcmetrics" \\
      -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \\
      -H "Content-Type: application/json" \\
      -d '{
        "sequencing_run_id": "240101_A00000_0001_FLOWCELLID",
        "metadata": { "pipeline": "bcl-convert", "version": "4.3" },
        "metrics": [{
          "name": "demux_summary",
          "values": {"total_reads": 800000000, "pf_reads": 750000000}
        }]
      }'
    ```

    **Sample association patterns:**
    - **Workflow-level**: Omit `samples` array (applies to entire pipeline run)
    - **Single sample**: One entry in `samples` array
    - **Sample pair**: Two entries with roles, e.g.,
        `[{"sample_name": "T1", "role": "tumor"},
          {"sample_name": "N1", "role": "normal"}]`

    **Duplicate detection:**
    If an equivalent record already exists for the same scope (same metadata),
    the existing record is returned instead of creating a duplicate.
    """
    return services.create_qcrecord(session, qcrecord_create, current_user.username)


@router.get(
    "/search",
    response_model=QCRecordsPublic,
    summary="Search QC records (GET)",
)
def search_qcrecords_get(
    session: SessionDep,
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    sequencing_run_id: Optional[str] = Query(
        None,
        description="Filter by sequencing run_id string (record or metric level)",
    ),
    workflow_run_id: Optional[str] = Query(
        None, description="Filter by workflow run ID (provenance)"
    ),
    latest: bool = Query(
        True,
        description="Return only newest record per scope (project or run)",
    ),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(100, ge=1, le=1000, description="Results per page"),
) -> QCRecordsPublic:
    """
    Search QC records using query parameters.

    **Parameters:**
    - `project_id`: Filter to records scoped to a specific project
    - `sequencing_run_id`: Filter by sequencing run_id string (record or metric level)
    - `workflow_run_id`: Filter by the workflow run that produced the QC data
    - `latest`: If true (default), returns only the most recent record per scope
    - `page`: Page number for pagination (starts at 1)
    - `per_page`: Number of results per page (max 1000)

    **Example:**
    ```
    GET /api/v1/qcmetrics/search?project_id=P-1234&latest=true
    GET /api/v1/qcmetrics/search?sequencing_run_id=240101_A00000_0001_XYZ
    GET /api/v1/qcmetrics/search?workflow_run_id=<uuid>&latest=false
    ```
    """
    filter_on = {}
    if project_id:
        filter_on["project_id"] = project_id
    if sequencing_run_id:
        filter_on["sequencing_run_id"] = sequencing_run_id
    if workflow_run_id:
        filter_on["workflow_run_id"] = workflow_run_id

    return services.search_qcrecords(
        session,
        filter_on=filter_on,
        page=page,
        per_page=per_page,
        latest=latest,
    )


@router.post(
    "/search",
    response_model=QCRecordsPublic,
    summary="Search QC records (POST)",
)
def search_qcrecords_post(
    session: SessionDep,
    search_request: QCRecordSearchRequest,
) -> QCRecordsPublic:
    """
    Search QC records using a JSON body for advanced filtering.

    **Request body format:**

    ```json
    {
      "filter_on": {
        "project_id": "P-1234",
        "metadata": {
          "pipeline": "RNA-Seq"
        }
      },
      "page": 1,
      "per_page": 100,
      "latest": true
    }
    ```

    **Filter options:**
    - `project_id`: Single value or list of project IDs
    - `sequencing_run_id`: Filter to records scoped to a sequencing run
    - `metadata`: Key-value pairs to match against pipeline metadata

    **Pagination:**
    - `page`: Page number (starts at 1)
    - `per_page`: Results per page (max 1000)

    **Latest filtering:**
    - `latest: true` (default): Returns only the newest QC record per scope
    - `latest: false`: Returns all matching records (full history)
    """
    return services.search_qcrecords(
        session,
        filter_on=search_request.filter_on,
        page=search_request.page,
        per_page=search_request.per_page,
        latest=search_request.latest,
    )


@router.get(
    "/{qcrecord_id}",
    response_model=QCRecordPublic,
    summary="Get QC record by ID",
)
def get_qcrecord(
    session: SessionDep,
    qcrecord_id: str,
) -> QCRecordPublic:
    """
    Retrieve a specific QC record by its UUID.

    Returns the full QC record including metadata, metrics, and output files.
    """
    return services.get_qcrecord_by_id(session, qcrecord_id)


@router.delete(
    "/{qcrecord_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete QC record",
)
def delete_qcrecord(
    session: SessionDep,
    qcrecord_id: str,
) -> dict:
    """
    Delete a QC record and all associated data.

    This permanently removes:
    - The QC record
    - All associated metadata
    - All associated metrics and metric values
    - All associated output file records

    **Warning:** This action cannot be undone.
    """
    return services.delete_qcrecord(session, qcrecord_id)
