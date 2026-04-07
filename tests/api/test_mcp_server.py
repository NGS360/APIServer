"""
Property-based tests for the MCP server.

Uses hypothesis to verify correctness properties across randomized inputs.
"""

from unittest.mock import patch, MagicMock
import httpx
import hypothesis
from hypothesis import given, settings, strategies as st
import pytest

from api.chat.mcp_server import create_mcp_server, _make_api_caller


# Strategy: printable JWT-like strings (non-empty, no whitespace)
jwt_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=200,
)


class TestJWTPassthrough:
    """
    Feature: ngs360-ai-chatbot, Property 1: JWT passthrough to MCP tools

    For any MCP tool invocation and any valid JWT string, the outgoing HTTP
    request to the NGS360 REST API SHALL include an Authorization: Bearer <jwt>
    header matching the JWT provided at MCP server initialization.

    Validates: Requirements 1.2, 1.5, 6.1, 6.2
    """

    @given(jwt=jwt_strategy)
    @settings(max_examples=100)
    def test_api_caller_passes_jwt_in_header(self, jwt: str):
        """The low-level API caller includes the exact JWT in every request."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        with patch("api.chat.mcp_server.httpx.request", return_value=mock_response) as mock_req:
            caller = _make_api_caller(jwt, "http://fake-api")
            caller("GET", "/projects")

            mock_req.assert_called_once()
            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
            assert headers["Authorization"] == f"Bearer {jwt}"

    @given(jwt=jwt_strategy)
    @settings(max_examples=100)
    def test_mcp_tool_list_projects_passes_jwt(self, jwt: str):
        """Calling the list_projects MCP tool forwards the JWT to httpx."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch("api.chat.mcp_server.httpx.request", return_value=mock_response) as mock_req:
            mcp = create_mcp_server(jwt, "http://fake-api")
            # Get the tool function from the registry and call it directly
            tools = {t.name: t for t in mcp._tool_manager.list_tools()}
            list_projects_tool = tools["list_projects"]
            list_projects_tool.fn()

            mock_req.assert_called_once()
            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
            assert headers["Authorization"] == f"Bearer {jwt}"

    @given(jwt=jwt_strategy)
    @settings(max_examples=100)
    def test_mcp_tool_get_project_passes_jwt(self, jwt: str):
        """Calling get_project MCP tool forwards the JWT to httpx."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "P-1"}
        mock_response.raise_for_status = MagicMock()

        with patch("api.chat.mcp_server.httpx.request", return_value=mock_response) as mock_req:
            mcp = create_mcp_server(jwt, "http://fake-api")
            tools = {t.name: t for t in mcp._tool_manager.list_tools()}
            tools["get_project"].fn(project_id="P-1")

            mock_req.assert_called_once()
            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
            assert headers["Authorization"] == f"Bearer {jwt}"

    @given(jwt=jwt_strategy)
    @settings(max_examples=100)
    def test_mcp_post_tool_passes_jwt(self, jwt: str):
        """Mutation tools (POST) also forward the JWT."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"job_id": "J-1"}
        mock_response.raise_for_status = MagicMock()

        with patch("api.chat.mcp_server.httpx.request", return_value=mock_response) as mock_req:
            mcp = create_mcp_server(jwt, "http://fake-api")
            tools = {t.name: t for t in mcp._tool_manager.list_tools()}
            tools["submit_demux_workflow"].fn(
                workflow_id="wf-1", run_barcode="RUN001"
            )

            mock_req.assert_called_once()
            call_kwargs = mock_req.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
            assert headers["Authorization"] == f"Bearer {jwt}"


# ---------------------------------------------------------------------------
# Unit tests for MCP tools
# Requirements: 1.1–1.5
# ---------------------------------------------------------------------------


class TestMCPToolSuccessResponses:
    """
    Verify each tool returns the expected data shape on success.
    Validates: Requirements 1.1, 1.3
    """

    def _get_tools(self, jwt="test-jwt", base_url="http://fake-api"):
        mcp = create_mcp_server(jwt, base_url)
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    def _mock_json_response(self, data, status_code=200):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.json.return_value = data
        resp.raise_for_status = MagicMock()
        return resp

    # -- Project tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_list_projects_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response([{"id": "P-1"}])
        tools = self._get_tools()
        result = tools["list_projects"].fn()
        assert isinstance(result, list)
        assert result[0]["id"] == "P-1"

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_project_returns_dict(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"project_id": "P-1", "name": "Test"}
        )
        tools = self._get_tools()
        result = tools["get_project"].fn(project_id="P-1")
        assert result["project_id"] == "P-1"

    @patch("api.chat.mcp_server.httpx.request")
    def test_search_projects_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response([])
        tools = self._get_tools()
        result = tools["search_projects"].fn(query="test")
        assert isinstance(result, list)

    # -- Run tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_list_runs_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            [{"barcode": "RUN001"}]
        )
        tools = self._get_tools()
        result = tools["list_runs"].fn()
        assert isinstance(result, list)

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_run_returns_dict(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"barcode": "RUN001"}
        )
        tools = self._get_tools()
        result = tools["get_run"].fn(run_barcode="RUN001")
        assert result["barcode"] == "RUN001"

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_run_samplesheet_returns_data(self, mock_req):
        mock_req.return_value = self._mock_json_response({"rows": []})
        tools = self._get_tools()
        result = tools["get_run_samplesheet"].fn(run_barcode="RUN001")
        assert "rows" in result

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_run_metrics_returns_data(self, mock_req):
        mock_req.return_value = self._mock_json_response({"metrics": []})
        tools = self._get_tools()
        result = tools["get_run_metrics"].fn(run_barcode="RUN001")
        assert "metrics" in result

    # -- Sample tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_project_samples_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            [{"sample_id": "S-1"}]
        )
        tools = self._get_tools()
        result = tools["get_project_samples"].fn(project_id="P-1")
        assert isinstance(result, list)

    # -- File tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_list_files_by_entity_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response([])
        tools = self._get_tools()
        result = tools["list_files_by_entity"].fn(
            entity_type="PROJECT", entity_id="P-1"
        )
        assert isinstance(result, list)

    @patch("api.chat.mcp_server.httpx.request")
    def test_browse_s3_files_returns_data(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"files": [], "folders": []}
        )
        tools = self._get_tools()
        result = tools["browse_s3_files"].fn(uri="s3://bucket/prefix")
        assert "files" in result

    @patch("api.chat.mcp_server.httpx.request")
    def test_download_file_returns_data(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"url": "https://signed-url"}
        )
        tools = self._get_tools()
        result = tools["download_file"].fn(path="s3://bucket/file.txt")
        assert "url" in result

    # -- Job tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_list_jobs_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response([])
        tools = self._get_tools()
        result = tools["list_jobs"].fn()
        assert isinstance(result, list)

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_job_returns_dict(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"job_id": "J-1", "status": "SUCCEEDED"}
        )
        tools = self._get_tools()
        result = tools["get_job"].fn(job_id="J-1")
        assert result["job_id"] == "J-1"

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_job_log_returns_data(self, mock_req):
        mock_req.return_value = self._mock_json_response({"log": "output"})
        tools = self._get_tools()
        result = tools["get_job_log"].fn(job_id="J-1")
        assert "log" in result

    # -- QC tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_search_qc_records_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response([])
        tools = self._get_tools()
        result = tools["search_qc_records"].fn()
        assert isinstance(result, list)

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_qc_record_returns_dict(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"qcrecord_id": "QC-1"}
        )
        tools = self._get_tools()
        result = tools["get_qc_record"].fn(qcrecord_id="QC-1")
        assert result["qcrecord_id"] == "QC-1"

    # -- Workflow tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_list_workflows_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response([])
        tools = self._get_tools()
        result = tools["list_workflows"].fn()
        assert isinstance(result, list)

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_workflow_returns_dict(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"workflow_id": "WF-1"}
        )
        tools = self._get_tools()
        result = tools["get_workflow"].fn(workflow_id="WF-1")
        assert result["workflow_id"] == "WF-1"

    @patch("api.chat.mcp_server.httpx.request")
    def test_list_workflow_runs_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response([])
        tools = self._get_tools()
        result = tools["list_workflow_runs"].fn(workflow_id="WF-1")
        assert isinstance(result, list)

    # -- Pipeline tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_list_pipelines_returns_list(self, mock_req):
        mock_req.return_value = self._mock_json_response([])
        tools = self._get_tools()
        result = tools["list_pipelines"].fn()
        assert isinstance(result, list)

    @patch("api.chat.mcp_server.httpx.request")
    def test_get_pipeline_returns_dict(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"pipeline_id": "PL-1"}
        )
        tools = self._get_tools()
        result = tools["get_pipeline"].fn(pipeline_id="PL-1")
        assert result["pipeline_id"] == "PL-1"

    # -- Search tools --

    @patch("api.chat.mcp_server.httpx.request")
    def test_cross_entity_search_returns_data(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"results": []}
        )
        tools = self._get_tools()
        result = tools["cross_entity_search"].fn(query="test")
        assert "results" in result

    # -- Action tools (mutations) --

    @patch("api.chat.mcp_server.httpx.request")
    def test_submit_demux_workflow_returns_data(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"job_id": "J-new"}
        )
        tools = self._get_tools()
        result = tools["submit_demux_workflow"].fn(
            workflow_id="wf-1", run_barcode="RUN001"
        )
        assert result["job_id"] == "J-new"

    @patch("api.chat.mcp_server.httpx.request")
    def test_submit_pipeline_job_returns_data(self, mock_req):
        mock_req.return_value = self._mock_json_response(
            {"job_id": "J-pipe"}
        )
        tools = self._get_tools()
        result = tools["submit_pipeline_job"].fn(
            project_id="P-1",
            action="run",
            platform="illumina",
            project_type="wgs",
        )
        assert result["job_id"] == "J-pipe"


class TestMCPToolErrorHandling:
    """
    Verify MCP tools return structured error dicts on API errors.
    Validates: Requirements 1.4
    """

    def _get_tools(self):
        mcp = create_mcp_server("test-jwt", "http://fake-api")
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    def _mock_http_error(self, status_code, detail="Not found"):
        """Create a mock that raises HTTPStatusError."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.text = detail
        resp.json.return_value = {"detail": detail}

        request = MagicMock(spec=httpx.Request)
        error = httpx.HTTPStatusError(
            message=f"{status_code}", request=request, response=resp
        )
        return error

    @patch("api.chat.mcp_server.httpx.request")
    def test_404_returns_error_dict(self, mock_req):
        """API 404 → structured error dict, no exception raised."""
        mock_req.side_effect = self._mock_http_error(404, "Project not found")
        # Need to make raise_for_status raise the error
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = self._mock_http_error(
            404, "Project not found"
        )
        mock_req.side_effect = None
        mock_req.return_value = mock_resp

        tools = self._get_tools()
        result = tools["get_project"].fn(project_id="P-9999")
        assert result["error"] == 404
        assert "message" in result

    @patch("api.chat.mcp_server.httpx.request")
    def test_500_returns_error_dict(self, mock_req):
        """API 500 → structured error dict."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.json.return_value = {"detail": "Internal Server Error"}

        request = MagicMock(spec=httpx.Request)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="500", request=request, response=mock_resp
        )
        mock_req.return_value = mock_resp

        tools = self._get_tools()
        result = tools["list_projects"].fn()
        assert result["error"] == 500
        assert "message" in result

    @patch("api.chat.mcp_server.httpx.request")
    def test_403_returns_error_dict(self, mock_req):
        """API 403 → structured error dict."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_resp.json.return_value = {"detail": "Forbidden"}

        request = MagicMock(spec=httpx.Request)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="403", request=request, response=mock_resp
        )
        mock_req.return_value = mock_resp

        tools = self._get_tools()
        result = tools["get_run"].fn(run_barcode="RUN001")
        assert result["error"] == 403


class TestMCPToolNetworkErrors:
    """
    Verify MCP tools handle network errors gracefully.
    Validates: Requirements 1.4
    """

    def _get_tools(self):
        mcp = create_mcp_server("test-jwt", "http://fake-api")
        return {t.name: t for t in mcp._tool_manager.list_tools()}

    @patch("api.chat.mcp_server.httpx.request")
    def test_connect_error_returns_503(self, mock_req):
        """Network connection failure → error dict with 503."""
        mock_req.side_effect = httpx.ConnectError("Connection refused")
        tools = self._get_tools()
        result = tools["list_projects"].fn()
        assert result["error"] == 503
        assert "Could not reach" in result["message"]

    @patch("api.chat.mcp_server.httpx.request")
    def test_request_error_returns_503(self, mock_req):
        """Generic request error → error dict with 503."""
        mock_req.side_effect = httpx.RequestError(
            "timeout", request=MagicMock(spec=httpx.Request)
        )
        tools = self._get_tools()
        result = tools["get_project"].fn(project_id="P-1")
        assert result["error"] == 503
        assert "Could not reach" in result["message"]

    @patch("api.chat.mcp_server.httpx.request")
    def test_network_error_on_post_tool(self, mock_req):
        """Network error on mutation tool → same graceful handling."""
        mock_req.side_effect = httpx.ConnectError("Connection refused")
        tools = self._get_tools()
        result = tools["submit_demux_workflow"].fn(
            workflow_id="wf-1", run_barcode="RUN001"
        )
        assert result["error"] == 503


class TestMCPServerToolRegistry:
    """Verify the MCP server exposes the expected set of tools."""

    def test_all_expected_tools_registered(self):
        """All ~25 tools are present in the registry."""
        mcp = create_mcp_server("jwt", "http://fake")
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}

        expected = {
            "list_projects", "get_project", "search_projects",
            "list_runs", "get_run", "search_runs",
            "get_run_samplesheet", "get_run_metrics",
            "get_project_samples",
            "list_files_by_entity", "browse_s3_files", "download_file",
            "list_jobs", "get_job", "get_job_log",
            "search_qc_records", "get_qc_record",
            "list_workflows", "get_workflow", "list_workflow_runs",
            "list_pipelines", "get_pipeline",
            "cross_entity_search",
            "submit_demux_workflow", "submit_pipeline_job",
        }
        assert expected.issubset(tool_names), (
            f"Missing tools: {expected - tool_names}"
        )

    def test_tool_count_at_least_25(self):
        """At least 25 tools are registered."""
        mcp = create_mcp_server("jwt", "http://fake")
        tools = list(mcp._tool_manager.list_tools())
        assert len(tools) >= 25


class TestAPICallerUnit:
    """Unit tests for the _make_api_caller helper."""

    def test_base_url_trailing_slash_stripped(self):
        """Base URL trailing slash is normalized."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()

        with patch("api.chat.mcp_server.httpx.request", return_value=mock_resp) as mock_req:
            caller = _make_api_caller("jwt", "http://api.example.com/api/v1/")
            caller("GET", "/projects")

            call_args = mock_req.call_args
            url = call_args.args[1] if len(call_args.args) > 1 else call_args[0][1]
            assert "//" not in url.replace("http://", "")

    def test_params_forwarded(self):
        """Query params are passed through to httpx."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("api.chat.mcp_server.httpx.request", return_value=mock_resp) as mock_req:
            caller = _make_api_caller("jwt", "http://api")
            caller("GET", "/projects", params={"page": 2, "per_page": 10})

            call_kwargs = mock_req.call_args.kwargs
            assert call_kwargs["params"] == {"page": 2, "per_page": 10}

    def test_json_body_forwarded(self):
        """JSON body is passed through for POST requests."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        with patch("api.chat.mcp_server.httpx.request", return_value=mock_resp) as mock_req:
            caller = _make_api_caller("jwt", "http://api")
            body = {"action": "run", "platform": "illumina"}
            caller("POST", "/actions/submit", json_body=body)

            call_kwargs = mock_req.call_args.kwargs
            assert call_kwargs["json"] == body
