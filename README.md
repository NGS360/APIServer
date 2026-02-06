# NGS360 API Server

This repository contains the code for the NGS360 API server, which provides a RESTful API for accessing and managing data related to Next Generation Sequencing (NGS) projects.

It uses FastAPI for building the API and SQLModel (SQLAlchemy + Pydantic) for database interactions.

## Directory Structure

- `main.py`: The main entry point for the FastAPI application. Configure routes, middleware and lifespan events here.
- `core/`: Contains core configurations, settings, and utilities used across the application.
- `api/{feature}/`: Contains the API models, routes, and services for each `{feature}`.
  - `models.py`: Defines the data models used in the API, including Pydantic models for request and response validation.
  - `routes.py`: Contains the FastAPI routes for handling HTTP requests related to the feature.
  - `services.py`: Contains the business logic and database interactions for the feature.

```text
APIServer/
├── main.py                  # Application entry point
├── core/                    # Core functionality 
│   ├── config.py            # Configuration settings
│   ├── db.py                # Database connection
│   ├── deps.py              # Dependency injection
│   ├── lifespan.py          # Application lifecycle
│   ├── logger.py            # Logging configuration
│   ├── opensearch.py        # OpenSearch integration
│   └── security.py          # Security utilities
└── api/                     # API endpoints by feature
    ├── auth/                # Authentication (OAuth2)
    ├── files/               # Unified file management
    ├── jobs/                # Batch job management
    ├── manifest/            # Manifest handling
    ├── platforms/           # Platform information
    ├── project/             # Project management
    ├── qcmetrics/           # QC metrics from pipelines
    ├── runs/                # Sequencing run management
    ├── samples/             # Sample management
    ├── search/              # Search capabilities
    ├── settings/            # System settings
    ├── vendors/             # Vendor management
    └── workflow/            # Workflow management
```

## Key Components

### FastAPI Setup (main.py)

- The entry point creates the FastAPI application
- Sets up CORS middleware for client communication
- Includes routers for different API features
- Configures the application lifespan for startup/shutdown tasks

### Database Integration (core/)

- Uses SQLModel (SQLAlchemy + Pydantic) for database operations
- Connects to a MySQL database (configured via environment variables)
- Database initialization happens on application startup
- Clean database session management through dependency injection

---

## API Features

### Project API (`api/project/`)

Manage NGS projects with unique identifiers and flexible attributes.

**Models**:
- `Project` - Main project entity with UUID primary key and human-readable `project_id`
- `ProjectAttribute` - Key-value attributes associated with projects

**Endpoints**:
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/project` | Create a new project with optional attributes |
| GET | `/project` | List projects with pagination and sorting |
| GET | `/project/{project_id}` | Get a single project by its project_id |

---

### Sample API (`api/samples/`)

Manage samples associated with projects.

**Models**:
- `Sample` - Main sample entity with UUID primary key, sample_id, project_id foreign-key to Project
- `SampleAttribute` - Key-value attributes associated with samples

**Endpoints**:
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/samples` | Create a new sample with optional attributes |
| GET | `/samples` | List samples with pagination and sorting |
| GET | `/samples/{sample_id}` | Get a single sample by its sample_id |

---

### QC Metrics API (`api/qcmetrics/`)

Store and query quality control metrics from bioinformatics pipeline executions. Supports workflow-level, single-sample, and multi-sample (paired) metrics.

**Models**:
- `QCRecord` - Main QC record entity, one per pipeline execution per project
- `QCRecordMetadata` - Key-value store for pipeline-level metadata (pipeline name, version, etc.)
- `QCMetric` - Named group of metrics (e.g., "alignment_stats", "somatic_variants")
- `QCMetricValue` - Individual metric values with dual storage (string + numeric for queries)
- `QCMetricSample` - Sample associations with optional roles (e.g., "tumor", "normal")

**Sample Association Patterns**:
- **Workflow-level**: No samples (applies to entire pipeline run)
- **Single sample**: One sample entry
- **Sample pair**: Two entries with roles (e.g., tumor/normal for somatic variant calling)

**Endpoints**:
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/qcmetrics` | Create a new QC record with metrics and output files |
| GET | `/qcmetrics/search` | Search QC records with query parameters |
| POST | `/qcmetrics/search` | Search QC records with JSON body for advanced filtering |
| GET | `/qcmetrics/{id}` | Get QC record by UUID |
| DELETE | `/qcmetrics/{id}` | Delete a QC record and all associated data |

**Example Request**:
```json
{
  "project_id": "P-1234",
  "metadata": {
    "pipeline": "RNA-Seq",
    "version": "2.0.0"
  },
  "metrics": [
    {
      "name": "alignment_stats",
      "samples": [{"sample_name": "Sample1"}],
      "values": {"reads": 50000000, "alignment_rate": 95.5}
    },
    {
      "name": "somatic_variants",
      "samples": [
        {"sample_name": "T1", "role": "tumor"},
        {"sample_name": "N1", "role": "normal"}
      ],
      "values": {"snv_count": 15234, "tmb": 8.5}
    }
  ],
  "output_files": [
    {
      "uri": "s3://bucket/path/file.bam",
      "size": 123456789,
      "samples": [{"sample_name": "Sample1"}],
      "hashes": {"md5": "abc123..."},
      "tags": {"type": "alignment"}
    }
  ]
}
```

---

### Files API (`api/files/`)

Unified file management supporting both file uploads and external file references. Uses a many-to-many entity association pattern for maximum flexibility.

**Models**:
- `File` - Core file entity with URI, size, timestamps, and storage backend
- `FileEntity` - Junction table linking files to entities (PROJECT, RUN, SAMPLE, QCRECORD)
- `FileHash` - Multi-algorithm hash storage (md5, sha256, etag)
- `FileTag` - Flexible key-value metadata (type, format, archived, public, description)
- `FileSample` - Sample associations with optional roles (tumor, normal, case, control)

**Key Features**:
- **Versioning**: Same URI can exist multiple times with different `created_on` timestamps
- **Many-to-many associations**: A file can belong to multiple entities
- **Flexible tagging**: Replace hardcoded boolean flags with key-value tags
- **Multi-algorithm hashes**: Store MD5, SHA-256, S3 ETags, etc.

**Endpoints**:
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/files` | Create a file record (external reference) |
| POST | `/files/upload` | Upload a file with optional content |
| GET | `/files` | List/search files by URI or entity |
| GET | `/files/list` | Browse S3 bucket/folder |
| GET | `/files/download` | Download file from S3 |
| GET | `/files/{id}` | Get file by UUID |
| GET | `/files/{id}/versions` | Get all versions of a file |

**Example: Create File Reference**:
```json
{
  "uri": "s3://bucket/path/sample1.bam",
  "size": 1234567890,
  "source": "s3://qc-outputs/pipeline-run-123/manifest.json",
  "entities": [
    {"entity_type": "QCRECORD", "entity_id": "uuid", "role": "output"}
  ],
  "samples": [
    {"sample_name": "Sample1", "role": null}
  ],
  "hashes": {"md5": "abc123...", "sha256": "def456..."},
  "tags": {"type": "alignment", "format": "bam"}
}
```

---

### Sequencing Runs API (`api/runs/`)

Manage sequencing run information and associated sample sheets.

**Endpoints**:
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/runs` | List sequencing runs |
| GET | `/runs/{barcode}` | Get run by barcode |
| POST | `/runs` | Create a new run |

---

### Authentication API (`api/auth/`)

OAuth2-based authentication supporting multiple providers.

**Documentation**: See [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for detailed setup instructions.

---

### Additional APIs

| API | Description |
|-----|-------------|
| `api/jobs/` | Batch job management for long-running tasks |
| `api/manifest/` | Manifest file handling |
| `api/platforms/` | Platform/instrument information |
| `api/search/` | Cross-entity search capabilities |
| `api/settings/` | System configuration settings |
| `api/vendors/` | Vendor management |
| `api/workflow/` | Workflow definitions and management |

---

## Modern FastAPI Patterns Used

1. **Dependency Injection**
   - Database sessions injected into endpoints using `Depends`
   - Type aliases used for cleaner parameter annotations (`SessionDep`)

2. **Pydantic Models**
   - Clear separation between database models, input models, and output models
   - Validation built into models

3. **Application Lifecycle Management**
   - `lifespan` context manager for startup/shutdown procedures
   - Database initialized on startup

4. **SQLModel Integration**
   - Modern ORM combining SQLAlchemy and Pydantic
   - Relationship management with cascade deletes

5. **Environment-based Configuration**
   - Settings loaded from environment variables
   - Pydantic-based configuration with computed values

6. **Error Handling**
   - Proper HTTP exceptions with status codes and descriptive messages
   - Validation of business rules

---

## Install

This application uses pyproject.toml and uv as the package manager.

### Development

To install this for development, use:

```bash
uv sync
```

This will create a Python virtual environment in .venv (by default) using the version of python listed in .python-version, and install the dependencies listed in pyproject.toml.

Make sure necessary environment variables are defined or present in .env, as needed in core/config.py, then run the service:

```bash
source .venv/bin/activate
fastapi dev main.py
```

### Unit Tests

```bash
uv sync --extra dev
pytest -xvs --cov
coverage html
open htmlcov/index.html
```

See [tests/TESTING_GUIDE.md](tests/TESTING_GUIDE.md) for detailed testing documentation.

### Docker Stack

Use the stack as described in docker-compose.yml to launch all components.

#### Environment Variables for Docker

The docker-compose.yml file uses environment variable substitution for AWS credentials. You have two options:

**Option 1: Use a .env file (Recommended for development)**

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your AWS credentials:
   ```bash
   AWS_ACCESS_KEY_ID=your_actual_access_key
   AWS_SECRET_ACCESS_KEY=your_actual_secret_key
   AWS_REGION=us-east-1
   ```

3. Launch the stack:
   ```bash
   docker-compose up
   ```

**Option 2: Export environment variables (Recommended for CI/CD)**

```bash
export AWS_ACCESS_KEY_ID=your_actual_access_key
export AWS_SECRET_ACCESS_KEY=your_actual_secret_key
export AWS_REGION=us-east-1
docker-compose up
```

**Note:** If no environment variables are set, the docker-compose file will use default values (`admin`/`admin`) suitable for local OpenSearch development.

#### OpenSearch SSL Configuration

The application supports different OpenSearch configurations for development and production:

**Local Development (Docker Compose)**
- Uses HTTP (no SSL) with security plugin disabled
- Set in `docker-compose.yml`:
  ```yaml
  - OPENSEARCH_USE_SSL=false
  - OPENSEARCH_VERIFY_CERTS=false
  ```

**Production (AWS OpenSearch Service)**
- Uses HTTPS with SSL/TLS enabled
- Configure in your production `.env` file or secrets manager:
  ```bash
  OPENSEARCH_USE_SSL=true
  OPENSEARCH_VERIFY_CERTS=true
  OPENSEARCH_USER=your_username
  OPENSEARCH_PASSWORD=your_password
  ```

These settings are controlled by environment variables and can be adjusted per environment without code changes.

---

## Documentation

Additional documentation is available in the `docs/` directory:

- [AUTHENTICATION.md](docs/AUTHENTICATION.md) - Authentication setup and configuration
- [OAuth2_Authorization_Code_Grant_Flow.md](docs/OAuth2_Authorization_Code_Grant_Flow.md) - OAuth2 flow details
- [SETUP.md](docs/SETUP.md) - Environment setup instructions
