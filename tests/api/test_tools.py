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

    def test_list_tools_s3_error_no_credentials(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test list tools when AWS credentials are missing"""
        mock_s3_client.simulate_error("NoCredentialsError")

        response = client.get("/api/v1/tools/")
        assert response.status_code == 401
        assert "credentials" in response.json()["detail"].lower()

    def test_list_tools_s3_error_no_bucket(self, client: TestClient, mock_s3_client: MockS3Client):
        """Test list tools when S3 bucket doesn't exist"""
        mock_s3_client.simulate_error("NoSuchBucket")

        response = client.get("/api/v1/tools/")
        assert response.status_code == 404
        assert "bucket" in response.json()["detail"].lower()

    def test_list_tools_s3_error_access_denied(self, client: TestClient, mock_s3_client: MockS3Client):
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
