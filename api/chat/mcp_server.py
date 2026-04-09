"""
MCP Server for NGS360 AI Chatbot.

Exposes ~25 NGS360 REST API endpoints as MCP tools for the Strands Agent.
Each tool forwards the user's JWT for authorization and returns structured
error dicts on failure instead of raising exceptions.
"""

from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP


def _make_api_caller(jwt_token: str, api_base_url: str):
    """
    Return a helper that makes HTTP requests to the NGS360 API
    with the user's JWT in the Authorization header.

    On HTTP errors (4xx/5xx), returns {"error": status_code, "message": detail}.
    On network errors, returns {"error": 503, "message": "Could not reach NGS360 API"}.
    """
    headers = {"Authorization": f"Bearer {jwt_token}"}
    base = api_base_url.rstrip("/")

    def call(
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{base}{path}"
        try:
            resp = httpx.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", exc.response.text)
            except Exception:
                detail = exc.response.text
            return {"error": exc.response.status_code, "message": detail}
        except httpx.ConnectError:
            return {"error": 503, "message": "Could not reach NGS360 API"}
        except httpx.RequestError:
            return {"error": 503, "message": "Could not reach NGS360 API"}

    return call



def create_mcp_server(jwt_token: str, api_base_url: str) -> FastMCP:
    """
    Create an MCP server instance with all NGS360 tools.

    Args:
        jwt_token: The user's JWT for API authorization.
        api_base_url: Base URL of the NGS360 API (e.g., "http://localhost:8000/api/v1").

    Returns:
        A FastMCP server ready to be used with Strands Agent.
    """
    mcp = FastMCP("ngs360")
    api = _make_api_caller(jwt_token, api_base_url)

    # ── Project tools ─────────────────────────────────────────────────────

    @mcp.tool()
    def list_projects(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "project_id",
        sort_order: str = "asc",
    ) -> Any:
        """List all projects with pagination."""
        return api("GET", "/projects", params={
            "page": page, "per_page": per_page,
            "sort_by": sort_by, "sort_order": sort_order,
        })

    @mcp.tool()
    def get_project(project_id: str) -> Any:
        """Get a single project by its project ID."""
        return api("GET", f"/projects/{project_id}")

    @mcp.tool()
    def search_projects(
        query: str,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> Any:
        """Search projects by project_id or name."""
        return api("GET", "/projects/search", params={
            "query": query, "page": page, "per_page": per_page,
            "sort_by": sort_by, "sort_order": sort_order,
        })

    # ── Run tools ─────────────────────────────────────────────────────────

    @mcp.tool()
    def list_runs(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "barcode",
        sort_order: str = "asc",
    ) -> Any:
        """List all sequencing runs with pagination."""
        return api("GET", "/runs", params={
            "page": page, "per_page": per_page,
            "sort_by": sort_by, "sort_order": sort_order,
        })

    @mcp.tool()
    def get_run(run_barcode: str) -> Any:
        """Get a sequencing run by its barcode."""
        return api("GET", f"/runs/{run_barcode}")

    @mcp.tool()
    def search_runs(
        query: str,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "barcode",
        sort_order: str = "asc",
    ) -> Any:
        """Search sequencing runs by barcode or experiment name."""
        return api("GET", "/runs/search", params={
            "query": query, "page": page, "per_page": per_page,
            "sort_by": sort_by, "sort_order": sort_order,
        })

    @mcp.tool()
    def get_run_samplesheet(run_barcode: str) -> Any:
        """Get the sample sheet for a sequencing run."""
        return api("GET", f"/runs/{run_barcode}/samplesheet")

    @mcp.tool()
    def get_run_metrics(run_barcode: str) -> Any:
        """Get demultiplexing metrics for a sequencing run."""
        return api("GET", f"/runs/{run_barcode}/metrics")

    # ── Sample tools ──────────────────────────────────────────────────────

    @mcp.tool()
    def get_project_samples(
        project_id: str,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "sample_id",
        sort_order: str = "asc",
    ) -> Any:
        """List samples belonging to a project."""
        return api("GET", f"/projects/{project_id}/samples", params={
            "page": page, "per_page": per_page,
            "sort_by": sort_by, "sort_order": sort_order,
        })

    # ── File tools ────────────────────────────────────────────────────────

    @mcp.tool()
    def list_files_by_entity(
        entity_type: str,
        entity_id: str,
        include_archived: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> Any:
        """List files associated with an entity (PROJECT, RUN, SAMPLE, QCRECORD, etc.)."""
        return api("GET", "/files", params={
            "entity_type": entity_type, "entity_id": entity_id,
            "include_archived": include_archived,
            "page": page, "per_page": per_page,
        })

    @mcp.tool()
    def browse_s3_files(uri: str) -> Any:
        """Browse files and folders at an S3 URI."""
        return api("GET", "/files/list", params={"uri": uri})

    @mcp.tool()
    def download_file(path: str) -> Any:
        """Get a download link / content for a file at the given S3 URI."""
        return api("GET", "/files/download", params={"path": path})

    # ── Job tools ─────────────────────────────────────────────────────────

    @mcp.tool()
    def list_jobs(
        skip: int = 0,
        limit: int = 100,
        user: str | None = None,
        status_filter: str | None = None,
        sort_by: str = "submitted_on",
        sort_order: str = "desc",
    ) -> Any:
        """List batch jobs with optional filtering."""
        params: dict[str, Any] = {
            "skip": skip, "limit": limit,
            "sort_by": sort_by, "sort_order": sort_order,
        }
        if user:
            params["user"] = user
        if status_filter:
            params["status_filter"] = status_filter
        return api("GET", "/jobs", params=params)

    @mcp.tool()
    def get_job(job_id: str) -> Any:
        """Get details of a specific batch job by UUID."""
        return api("GET", f"/jobs/{job_id}")

    @mcp.tool()
    def get_job_log(job_id: str) -> Any:
        """Get the log output for a batch job."""
        return api("GET", f"/jobs/{job_id}/log")

    # ── QC Metrics tools ──────────────────────────────────────────────────

    @mcp.tool()
    def search_qc_records(
        project_id: str | None = None,
        sequencing_run_barcode: str | None = None,
        workflow_run_id: str | None = None,
        latest: bool = True,
        page: int = 1,
        per_page: int = 100,
    ) -> Any:
        """Search QC metric records with optional filters."""
        params: dict[str, Any] = {
            "latest": latest, "page": page, "per_page": per_page,
        }
        if project_id:
            params["project_id"] = project_id
        if sequencing_run_barcode:
            params["sequencing_run_barcode"] = sequencing_run_barcode
        if workflow_run_id:
            params["workflow_run_id"] = workflow_run_id
        return api("GET", "/qcmetrics/search", params=params)

    @mcp.tool()
    def get_qc_record(qcrecord_id: str) -> Any:
        """Get a specific QC record by its ID."""
        return api("GET", f"/qcmetrics/{qcrecord_id}")

    # ── Workflow tools ────────────────────────────────────────────────────

    @mcp.tool()
    def list_workflows(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> Any:
        """List all workflows with pagination."""
        return api("GET", "/workflows", params={
            "page": page, "per_page": per_page,
            "sort_by": sort_by, "sort_order": sort_order,
        })

    @mcp.tool()
    def get_workflow(workflow_id: str) -> Any:
        """Get a single workflow by its ID."""
        return api("GET", f"/workflows/{workflow_id}")

    @mcp.tool()
    def list_workflow_runs(
        workflow_id: str,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Any:
        """List execution runs for a workflow."""
        return api("GET", f"/workflows/{workflow_id}/runs", params={
            "page": page, "per_page": per_page,
            "sort_by": sort_by, "sort_order": sort_order,
        })

    # ── Pipeline tools ────────────────────────────────────────────────────

    @mcp.tool()
    def list_pipelines(
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> Any:
        """List all pipelines with pagination."""
        return api("GET", "/pipelines", params={
            "page": page, "per_page": per_page,
            "sort_by": sort_by, "sort_order": sort_order,
        })

    @mcp.tool()
    def get_pipeline(pipeline_id: str) -> Any:
        """Get a single pipeline by its ID."""
        return api("GET", f"/pipelines/{pipeline_id}")

    # ── Search tools ──────────────────────────────────────────────────────

    @mcp.tool()
    def cross_entity_search(query: str, n_results: int = 5) -> Any:
        """Search across all entity types (projects, runs, samples, etc.)."""
        return api("GET", "/search", params={
            "query": query, "n_results": n_results,
        })

    # ── Action tools (mutations) ──────────────────────────────────────────

    @mcp.tool()
    def list_demux_configs() -> Any:
        """List available demultiplexing workflow configurations. Returns a list of workflow config IDs that can be used with submit_demux_workflow."""
        return api("GET", "/runs/demultiplex")

    @mcp.tool()
    def get_demux_config(
        workflow_id: str,
        run_barcode: str | None = None,
    ) -> Any:
        """Get a specific demultiplexing workflow configuration by ID. Optionally pass a run_barcode to prepopulate the s3_run_folder_path input."""
        params: dict[str, Any] = {}
        if run_barcode:
            params["run_barcode"] = run_barcode
        return api("GET", f"/runs/demultiplex/{workflow_id}", params=params)

    @mcp.tool()
    def submit_demux_workflow(
        workflow_id: str,
        run_barcode: str,
        inputs: dict[str, Any] | None = None,
    ) -> Any:
        """Submit a demultiplexing workflow job for a sequencing run. This is a write operation — confirm with the user before calling."""
        body: dict[str, Any] = {
            "workflow_id": workflow_id,
            "run_barcode": run_barcode,
        }
        if inputs:
            body["inputs"] = inputs
        return api("POST", "/runs/demultiplex", json_body=body)

    @mcp.tool()
    def submit_pipeline_job(
        project_id: str,
        action: str,
        platform: str,
        project_type: str,
        reference: str | None = None,
        auto_release: bool = False,
    ) -> Any:
        """Submit a pipeline job for a project. This is a write operation — confirm with the user before calling."""
        body: dict[str, Any] = {
            "action": action,
            "platform": platform,
            "project_type": project_type,
            "auto_release": auto_release,
        }
        if reference:
            body["reference"] = reference
        return api("POST", f"/projects/{project_id}/actions/submit", json_body=body)

    return mcp
