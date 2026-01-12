"""
Test /tools endpoint
"""

from fastapi.testclient import TestClient
import pytest

from tests.conftest import MockS3Client
from api.tools.models import ToolConfig, ToolConfigInput, InputType, AwsBatchConfig


class TestToolsAPI:
    """Test tools API endpoints"""

    def test_list_tools_empty(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test listing tools when bucket is empty"""
        # Setup empty bucket
        mock_s3_client.setup_bucket("test-tool-configs-bucket", "", [], [])

        response = client.get("/api/v1/tools/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_list_tools_with_configs(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test listing tools when multiple configs exist"""
        # Setup bucket with multiple tool config files
        files = [
            {
                "Key": "bcl2fastq.yaml",
                "LastModified": "2024-01-01T12:00:00",
                "Size": 1024,
            },
            {
                "Key": "cellranger-mkfastq.yaml",
                "LastModified": "2024-01-02T12:00:00",
                "Size": 2048,
            },
            {
                "Key": "ontbasecalling.yml",
                "LastModified": "2024-01-03T12:00:00",
                "Size": 1536,
            },
            # Non-yaml files should be ignored
            {
                "Key": "README.md",
                "LastModified": "2024-01-04T12:00:00",
                "Size": 512,
            },
        ]
        mock_s3_client.setup_bucket("test-tool-configs-bucket", "", files, [])

        response = client.get("/api/v1/tools/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3
        assert "bcl2fastq" in data
        assert "cellranger-mkfastq" in data
        assert "ontbasecalling" in data
        assert "README" not in data  # Non-yaml files excluded

    def test_get_tool_config_basic(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test retrieving a tool config without aws_batch section"""
        # Create a basic tool config without aws_batch
        tool_config_yaml = """
version: 1
tool_id: bcl2fastq
tool_name: BCL to FASTQ
tool_description: Demultiplex Illumina Runs
inputs:
  - name: s3_run_folder_path
    desc: S3 Run Folder Path
    type: String
    required: true
  - name: command_line_options
    desc: Command-Line Options
    type: String
    default: --barcode-mismatches=1
  - name: assay_method
    desc: Assay Method
    type: Enum
    options:
      - RNA-Seq
      - WES
      - WGS
    required: true
help: Run Illumina bcl2fastq on an Illumina run
tags:
  - name: illumina_run
"""
        # Store in mock S3
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="bcl2fastq.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/tools/bcl2fastq")
        assert response.status_code == 200
        data = response.json()

        assert data["version"] == 1
        assert data["tool_id"] == "bcl2fastq"
        assert data["tool_name"] == "BCL to FASTQ"
        assert data["tool_description"] == "Demultiplex Illumina Runs"
        assert data["help"] == "Run Illumina bcl2fastq on an Illumina run"
        assert len(data["inputs"]) == 3
        assert len(data["tags"]) == 1
        assert data["tags"][0]["name"] == "illumina_run"
        # aws_batch should be None when not present
        assert data.get("aws_batch") is None

    def test_get_tool_config_with_aws_batch(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test retrieving a tool config with aws_batch section"""
        # Create a tool config WITH aws_batch
        tool_config_yaml = """
version: 1
tool_id: cellranger-mkfastq
tool_name: CellRanger mkfastq
tool_description: Demultiplex Illumina run with CellRanger
inputs:
  - name: s3_run_folder_path
    desc: S3 Run Folder Path
    type: String
    required: true
  - name: barcode_mismatches
    desc: Barcode Mismatches
    type: Integer
    default: 1
help: Run cellranger mkfastq on an Illumina run
tags:
  - name: illumina_run
aws_batch:
  job_name: cellranger-mkfastq-test
  job_definition: ngs360-cellranger:11
  job_queue: cellRangerJobQueue-2fe9b27d39b85fa
  command: mkfastq.sh
  environment:
    - name: S3_RUNFOLDER_PATH
      value: "{{ s3_run_folder_path }}"
    - name: MKFASTQ_OPTS
      value: --barcode-mismatches={{ barcode_mismatches }}
    - name: USER
      value: "{{ user }}"
"""
        # Store in mock S3
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="cellranger-mkfastq.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/tools/cellranger-mkfastq")
        assert response.status_code == 200
        data = response.json()

        assert data["version"] == 1
        assert data["tool_id"] == "cellranger-mkfastq"
        assert data["tool_name"] == "CellRanger mkfastq"

        # Verify aws_batch section is present and correct
        assert "aws_batch" in data
        assert data["aws_batch"] is not None
        aws_batch = data["aws_batch"]
        assert aws_batch["job_name"] == "cellranger-mkfastq-test"
        assert aws_batch["job_definition"] == "ngs360-cellranger:11"
        assert aws_batch["job_queue"] == "cellRangerJobQueue-2fe9b27d39b85fa"
        assert aws_batch["command"] == "mkfastq.sh"

        # Verify environment variables
        assert "environment" in aws_batch
        assert len(aws_batch["environment"]) == 3
        env_vars = {env["name"]: env["value"] for env in aws_batch["environment"]}
        assert "S3_RUNFOLDER_PATH" in env_vars
        assert env_vars["S3_RUNFOLDER_PATH"] == "{{ s3_run_folder_path }}"
        assert "MKFASTQ_OPTS" in env_vars
        assert env_vars["MKFASTQ_OPTS"] == "--barcode-mismatches={{ barcode_mismatches }}"
        assert "USER" in env_vars
        assert env_vars["USER"] == "{{ user }}"

    def test_get_tool_config_with_aws_batch_no_environment(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test retrieving a tool config with aws_batch but no environment section"""
        # Create a tool config with minimal aws_batch (no environment vars)
        tool_config_yaml = """
version: 1
tool_id: simple-tool
tool_name: Simple Tool
tool_description: A simple tool
inputs:
  - name: input_file
    desc: Input File
    type: String
    required: true
help: Simple tool help
tags:
  - name: basic
aws_batch:
  job_name: simple-job
  job_definition: simple-def:1
  job_queue: simple-queue
  command: run.sh
"""
        # Store in mock S3
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="simple-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/tools/simple-tool")
        assert response.status_code == 200
        data = response.json()

        # Verify aws_batch section is present but environment is None or empty
        assert "aws_batch" in data
        aws_batch = data["aws_batch"]
        assert aws_batch["job_name"] == "simple-job"
        assert aws_batch["command"] == "run.sh"
        # environment should be None or empty list
        assert aws_batch.get("environment") is None or aws_batch.get("environment") == []

    def test_get_tool_config_yml_extension(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test retrieving a tool config with .yml extension (not .yaml)"""
        tool_config_yaml = """
version: 1
tool_id: ont-tool
tool_name: ONT Tool
tool_description: Oxford Nanopore Tool
inputs:
  - name: input_path
    desc: Input Path
    type: String
    required: true
help: ONT basecalling
tags:
  - name: ont
"""
        # Store with .yml extension
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="ont-tool.yml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/tools/ont-tool")
        assert response.status_code == 200
        data = response.json()
        assert data["tool_id"] == "ont-tool"

    def test_get_tool_config_not_found(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test retrieving a non-existent tool config"""
        response = client.get("/api/v1/tools/nonexistent-tool")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_tool_config_invalid_yaml(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test retrieving a tool config with invalid YAML"""
        # Use YAML with unclosed bracket to ensure parse error
        invalid_yaml = """
version: 1
tool_id: broken-tool
inputs: [
  missing closing bracket
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="broken-tool.yaml",
            Body=invalid_yaml.encode("utf-8"),
        )

        response = client.get("/api/v1/tools/broken-tool")
        assert response.status_code == 422
        assert "yaml" in response.json()["detail"].lower()

    def test_list_tools_s3_error_no_credentials(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test list tools when AWS credentials are missing"""
        mock_s3_client.simulate_error("NoCredentialsError")

        response = client.get("/api/v1/tools/")
        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()

    def test_list_tools_s3_error_no_bucket(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test list tools when S3 bucket doesn't exist"""
        mock_s3_client.simulate_error("NoSuchBucket")

        response = client.get("/api/v1/tools/")
        assert response.status_code == 404
        assert "bucket" in response.json()["detail"].lower()

    def test_list_tools_s3_error_access_denied(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test list tools when access is denied"""
        mock_s3_client.simulate_error("AccessDenied")

        response = client.get("/api/v1/tools/")
        assert response.status_code == 403
        assert "denied" in response.json()["detail"].lower()

    def test_get_tool_config_s3_error_no_credentials(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test get tool config when AWS credentials are missing"""
        mock_s3_client.simulate_error("NoCredentialsError")

        response = client.get("/api/v1/tools/some-tool")
        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()


class TestToolConfigModels:
    """Test Pydantic models for tool configs"""

    def test_tool_config_input_enum_requires_options(self):
        """Test that Enum input type requires options"""
        from pydantic import ValidationError

        # This should fail - Enum without options
        with pytest.raises(ValidationError) as exc_info:
            ToolConfigInput(
                name="assay",
                desc="Assay Type",
                type=InputType.ENUM,
                required=True,
            )

        # Verify the error mentions options
        assert "options" in str(exc_info.value).lower()

    def test_tool_config_input_enum_with_options(self):
        """Test that Enum input type works with options"""
        input_config = ToolConfigInput(
            name="assay",
            desc="Assay Type",
            type=InputType.ENUM,
            required=True,
            options=["RNA-Seq", "WES", "WGS"],
        )
        assert input_config.name == "assay"
        assert input_config.type == InputType.ENUM
        assert len(input_config.options) == 3

    def test_tool_config_input_string_type(self):
        """Test String input type doesn't require options"""
        input_config = ToolConfigInput(
            name="file_path",
            desc="File Path",
            type=InputType.STRING,
            required=True,
        )
        assert input_config.name == "file_path"
        assert input_config.type == InputType.STRING
        assert input_config.options is None

    def test_tool_config_input_integer_type(self):
        """Test Integer input type"""
        input_config = ToolConfigInput(
            name="threads",
            desc="Number of threads",
            type=InputType.INTEGER,
            default=4,
        )
        assert input_config.name == "threads"
        assert input_config.type == InputType.INTEGER
        assert input_config.default == 4

    def test_tool_config_input_boolean_type(self):
        """Test Boolean input type"""
        input_config = ToolConfigInput(
            name="verbose",
            desc="Verbose output",
            type=InputType.BOOLEAN,
            default=False,
        )
        assert input_config.name == "verbose"
        assert input_config.type == InputType.BOOLEAN
        assert input_config.default is False

    def test_aws_batch_environment_model(self):
        """Test AwsBatchEnvironment model"""
        from api.tools.models import AwsBatchEnvironment

        env = AwsBatchEnvironment(
            name="MY_VAR",
            value="my_value"
        )
        assert env.name == "MY_VAR"
        assert env.value == "my_value"

    def test_aws_batch_config_minimal(self):
        """Test AwsBatchConfig with minimal required fields"""
        aws_config = AwsBatchConfig(
            job_name="test-job",
            job_definition="test-def:1",
            job_queue="test-queue",
            command="run.sh",
        )
        assert aws_config.job_name == "test-job"
        assert aws_config.job_definition == "test-def:1"
        assert aws_config.job_queue == "test-queue"
        assert aws_config.command == "run.sh"
        assert aws_config.environment is None

    def test_aws_batch_config_with_environment(self):
        """Test AwsBatchConfig with environment variables"""
        from api.tools.models import AwsBatchEnvironment

        env_vars = [
            AwsBatchEnvironment(name="VAR1", value="value1"),
            AwsBatchEnvironment(name="VAR2", value="value2"),
        ]

        aws_config = AwsBatchConfig(
            job_name="test-job",
            job_definition="test-def:1",
            job_queue="test-queue",
            command="run.sh",
            environment=env_vars,
        )

        assert len(aws_config.environment) == 2
        assert aws_config.environment[0].name == "VAR1"
        assert aws_config.environment[1].value == "value2"

    def test_tool_config_complete_with_aws_batch(self):
        """Test complete ToolConfig with aws_batch"""
        from api.tools.models import ToolConfigTag, AwsBatchEnvironment

        tool_config = ToolConfig(
            version=1,
            tool_id="test-tool",
            tool_name="Test Tool",
            tool_description="A test tool",
            inputs=[
                ToolConfigInput(
                    name="input1",
                    desc="Input 1",
                    type=InputType.STRING,
                    required=True,
                )
            ],
            help="Help text",
            tags=[ToolConfigTag(name="test")],
            aws_batch=AwsBatchConfig(
                job_name="test-job",
                job_definition="test-def:1",
                job_queue="test-queue",
                command="run.sh",
                environment=[
                    AwsBatchEnvironment(name="VAR1", value="value1")
                ],
            ),
        )

        assert tool_config.version == 1
        assert tool_config.tool_id == "test-tool"
        assert tool_config.aws_batch is not None
        assert tool_config.aws_batch.job_name == "test-job"
        assert len(tool_config.aws_batch.environment) == 1

    def test_tool_config_without_aws_batch(self):
        """Test ToolConfig without aws_batch (should be None)"""
        from api.tools.models import ToolConfigTag

        tool_config = ToolConfig(
            version=1,
            tool_id="test-tool",
            tool_name="Test Tool",
            tool_description="A test tool",
            inputs=[
                ToolConfigInput(
                    name="input1",
                    desc="Input 1",
                    type=InputType.STRING,
                    required=True,
                )
            ],
            help="Help text",
            tags=[ToolConfigTag(name="test")],
        )

        assert tool_config.version == 1
        assert tool_config.tool_id == "test-tool"
        assert tool_config.aws_batch is None


class TestSubmitJobEndpoint:
    """Test the submit job endpoint and related services"""

    def test_submit_job_success(
        self, client: TestClient, mock_s3_client: MockS3Client, monkeypatch
    ):
        """Test successful job submission"""
        # Setup tool config with aws_batch
        tool_config_yaml = """
version: 1
tool_id: cellranger-mkfastq
tool_name: CellRanger mkfastq
tool_description: Demultiplex Illumina run with CellRanger
inputs:
  - name: s3_run_folder_path
    desc: S3 Run Folder Path
    type: String
    required: true
  - name: barcode_mismatches
    desc: Barcode Mismatches
    type: Integer
    default: 1
  - name: user
    desc: User
    type: String
    required: true
help: Run cellranger mkfastq on an Illumina run
tags:
  - name: illumina_run
aws_batch:
  job_name: cellranger-mkfastq-{{ s3_run_folder_path.split('/')[-1] }}
  job_definition: ngs360-cellranger:11
  job_queue: cellRangerJobQueue-2fe9b27d39b85fa
  command: mkfastq.sh
  environment:
    - name: S3_RUNFOLDER_PATH
      value: "{{ s3_run_folder_path }}"
    - name: MKFASTQ_OPTS
      value: --barcode-mismatches={{ barcode_mismatches }}
    - name: USER
      value: "{{ user }}"
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="cellranger-mkfastq.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        # Mock boto3 batch client
        mock_batch_response = {
            "jobId": "test-job-123",
            "jobName": "cellranger-mkfastq-test-run",
        }

        class MockBatchClient:
            def submit_job(self, **kwargs):
                return mock_batch_response

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        # Submit job
        request_body = {
            "tool_id": "cellranger-mkfastq",
            "run_barcode": "190110_MACHINE123_0001_FLOWCELL123",
            "inputs": {
                "s3_run_folder_path": "s3://bucket/test-run",
                "barcode_mismatches": 1,
                "user": "testuser",
            },
        }

        response = client.post(
            "/api/v1/tools/submit", json=request_body
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jobId"] == "test-job-123"
        assert data["jobName"] == "cellranger-mkfastq-test-run"
        assert "jobCommand" in data
        assert data["jobCommand"] == "mkfastq.sh"

    def test_submit_job_with_jinja_expressions(
        self, client: TestClient, mock_s3_client: MockS3Client, monkeypatch
    ):
        """Test job submission with Jinja2 expressions in template"""
        tool_config_yaml = """
version: 1
tool_id: test-tool
tool_name: Test Tool
tool_description: Test tool with Jinja expressions
inputs:
  - name: s3_path
    desc: S3 Path
    type: String
    required: true
  - name: max_reads
    desc: Max Reads
    type: Integer
    default: 1000
help: Test tool
tags:
  - name: test
aws_batch:
  job_name: test-{{ s3_path.split('/')[-1] }}-{{ max_reads }}
  job_definition: test-def:1
  job_queue: test-queue
  command: run.sh {{ max_reads }}
  environment:
    - name: S3_PATH
      value: "{{ s3_path }}"
    - name: MAX_READS
      value: "{{ max_reads }}"
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="test-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        # Mock batch client
        captured_submit_args = {}

        class MockBatchClient:
            def submit_job(self, **kwargs):
                captured_submit_args.update(kwargs)
                return {"jobId": "job-456", "jobName": kwargs["jobName"]}

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        request_body = {
            "tool_id": "test-tool",
            "run_barcode": "test-run-123",
            "inputs": {
                "s3_path": "s3://bucket/folder/subfolder/file.txt",
                "max_reads": 5000,
            },
        }

        response = client.post("/api/v1/tools/submit", json=request_body)

        assert response.status_code == 200
        data = response.json()

        # Verify Jinja2 expression was evaluated correctly
        assert data["jobName"] == "test-file.txt-5000"
        assert data["jobCommand"] == "run.sh 5000"

        # Verify container overrides
        assert "containerOverrides" in captured_submit_args
        overrides = captured_submit_args["containerOverrides"]
        assert overrides["command"] == ["run.sh", "5000"]
        assert len(overrides["environment"]) == 2
        env_dict = {e["name"]: e["value"] for e in overrides["environment"]}
        assert env_dict["S3_PATH"] == "s3://bucket/folder/subfolder/file.txt"
        assert env_dict["MAX_READS"] == "5000"

    def test_submit_job_tool_not_found(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test job submission when tool config doesn't exist"""
        request_body = {
            "tool_id": "non-existent-tool",
            "run_barcode": "test-run",
            "inputs": {"param": "value"},
        }

        response = client.post(
            "/api/v1/tools/submit", json=request_body
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_submit_job_no_aws_batch_config(
        self, client: TestClient, mock_s3_client: MockS3Client
    ):
        """Test job submission when tool has no AWS Batch configuration"""
        tool_config_yaml = """
version: 1
tool_id: no-batch-tool
tool_name: No Batch Tool
tool_description: Tool without AWS Batch config
inputs:
  - name: input1
    desc: Input 1
    type: String
    required: true
help: Help text
tags:
  - name: test
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="no-batch-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        request_body = {
            "tool_id": "no-batch-tool",
            "run_barcode": "test-run",
            "inputs": {"input1": "value1"},
        }

        response = client.post("/api/v1/tools/submit", json=request_body)

        assert response.status_code == 400
        data = response.json()
        assert "not configured for AWS Batch" in data["detail"]

    def test_submit_job_batch_client_error(
        self, client: TestClient, mock_s3_client: MockS3Client, monkeypatch
    ):
        """Test job submission when AWS Batch client raises an error"""
        tool_config_yaml = """
version: 1
tool_id: batch-error-tool
tool_name: Batch Error Tool
tool_description: Tool that will cause batch error
inputs:
  - name: input1
    desc: Input 1
    type: String
    required: true
help: Help text
tags:
  - name: test
aws_batch:
  job_name: test-job
  job_definition: test-def:1
  job_queue: test-queue
  command: run.sh
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="batch-error-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        # Mock batch client that raises error
        from botocore.exceptions import ClientError

        class MockBatchClient:
            def submit_job(self, **kwargs):
                raise ClientError(
                    {
                        "Error": {
                            "Code": "InvalidParameterValueException",
                            "Message": "Invalid job definition",
                        }
                    },
                    "SubmitJob",
                )

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        request_body = {
            "tool_id": "batch-error-tool",
            "run_barcode": "test-run",
            "inputs": {"input1": "value1"},
        }

        response = client.post(
            "/api/v1/tools/submit", json=request_body
        )

        assert response.status_code == 500
        data = response.json()
        assert "Failed to submit job" in data["detail"]

    def test_submit_job_with_empty_environment(
        self, client: TestClient, mock_s3_client: MockS3Client, monkeypatch
    ):
        """Test job submission with no environment variables"""
        tool_config_yaml = """
version: 1
tool_id: no-env-tool
tool_name: No Environment Tool
tool_description: Tool with no environment vars
inputs:
  - name: input1
    desc: Input 1
    type: String
    required: true
help: Help text
tags:
  - name: test
aws_batch:
  job_name: no-env-job
  job_definition: test-def:1
  job_queue: test-queue
  command: run.sh
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="no-env-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        captured_submit_args = {}

        class MockBatchClient:
            def submit_job(self, **kwargs):
                captured_submit_args.update(kwargs)
                return {"jobId": "job-789", "jobName": kwargs["jobName"]}

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        request_body = {
            "tool_id": "no-env-tool",
            "run_barcode": "test-run",
            "inputs": {"input1": "value1"},
        }

        response = client.post("/api/v1/tools/submit", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["jobId"] == "job-789"

        # Verify environment is empty list
        overrides = captured_submit_args["containerOverrides"]
        assert overrides["environment"] == []

    def test_submit_job_invalid_request_body(self, client: TestClient):
        """Test job submission with invalid request body"""
        # Missing required field 'inputs'
        invalid_body = {
            "tool_id": "test-tool",
            "run_barcode": "test-run",
        }

        response = client.post("/api/v1/tools/submit", json=invalid_body)

        assert response.status_code == 422  # Validation error

    def test_submit_job_with_complex_inputs(
        self, client: TestClient, mock_s3_client: MockS3Client, monkeypatch
    ):
        """Test job submission with various input types"""
        tool_config_yaml = """
version: 1
tool_id: complex-tool
tool_name: Complex Tool
tool_description: Tool with complex inputs
inputs:
  - name: string_input
    desc: String Input
    type: String
    required: true
  - name: int_input
    desc: Integer Input
    type: Integer
    required: true
  - name: bool_input
    desc: Boolean Input
    type: Boolean
    required: false
  - name: enum_input
    desc: Enum Input
    type: Enum
    options:
      - option1
      - option2
    required: true
help: Help text
tags:
  - name: test
aws_batch:
  job_name: complex-{{ string_input }}-{{ int_input }}
  job_definition: test-def:1
  job_queue: test-queue
  command: run.sh
  environment:
    - name: STRING_VAL
      value: "{{ string_input }}"
    - name: INT_VAL
      value: "{{ int_input }}"
    - name: BOOL_VAL
      value: "{{ bool_input }}"
    - name: ENUM_VAL
      value: "{{ enum_input }}"
"""
        mock_s3_client.put_object(
            Bucket="test-tool-configs-bucket",
            Key="complex-tool.yaml",
            Body=tool_config_yaml.encode("utf-8"),
        )

        captured_submit_args = {}

        class MockBatchClient:
            def submit_job(self, **kwargs):
                captured_submit_args.update(kwargs)
                return {"jobId": "job-complex", "jobName": kwargs["jobName"]}

        def mock_boto3_client(service_name, region_name=None):
            if service_name == "batch":
                return MockBatchClient()
            return None

        monkeypatch.setattr("boto3.client", mock_boto3_client)

        request_body = {
            "tool_id": "complex-tool",
            "run_barcode": "test-run",
            "inputs": {
                "string_input": "test_string",
                "int_input": 42,
                "bool_input": True,
                "enum_input": "option2",
            },
        }

        response = client.post("/api/v1/tools/submit", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["jobName"] == "complex-test_string-42"

        # Verify environment variables have correct values
        overrides = captured_submit_args["containerOverrides"]
        env_dict = {e["name"]: e["value"] for e in overrides["environment"]}
        assert env_dict["STRING_VAL"] == "test_string"
        assert env_dict["INT_VAL"] == "42"
        assert env_dict["BOOL_VAL"] == "True"
        assert env_dict["ENUM_VAL"] == "option2"


class TestInterpolateFunction:
    """Test the interpolate helper function"""

    def test_interpolate_simple_substitution(self):
        """Test simple variable substitution"""
        from api.tools.services import interpolate

        template = "Hello {{ name }}"
        inputs = {"name": "World"}
        result = interpolate(template, inputs)
        assert result == "Hello World"

    def test_interpolate_multiple_variables(self):
        """Test multiple variable substitution"""
        from api.tools.services import interpolate

        template = "{{ greeting }} {{ name }}, you are {{ age }} years old"
        inputs = {"greeting": "Hello", "name": "Alice", "age": 30}
        result = interpolate(template, inputs)
        assert result == "Hello Alice, you are 30 years old"

    def test_interpolate_with_expression(self):
        """Test Jinja2 expressions"""
        from api.tools.services import interpolate

        template = "Last part: {{ path.split('/')[-1] }}"
        inputs = {"path": "s3://bucket/folder/file.txt"}
        result = interpolate(template, inputs)
        assert result == "Last part: file.txt"

    def test_interpolate_strips_whitespace(self):
        """Test that result is stripped of leading/trailing whitespace"""
        from api.tools.services import interpolate

        template = "  {{ value }}  "
        inputs = {"value": "test"}
        result = interpolate(template, inputs)
        assert result == "test"  # Whitespace stripped from rendered output

    def test_interpolate_with_missing_variable(self):
        """Test behavior when variable is missing"""
        from api.tools.services import interpolate

        template = "Hello {{ missing_var }}"
        inputs = {"name": "World"}

        # Jinja2 by default renders undefined variables as empty strings
        # in sandboxed mode
        result = interpolate(template, inputs)
        # The sandboxed environment should handle missing variables
        # gracefully
        assert "Hello" in result
