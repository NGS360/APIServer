# Workflows, Versions, Aliases, Registrations & Runs

This document describes the Workflow system for defining, versioning, registering, and tracking executions of bioinformatics workflows across multiple compute platforms.

## Overview

The Workflow system provides:

- **Platform-agnostic workflow identity**: Define a workflow once by name
- **Explicit versioning**: Each version carries its own `definition_uri` (WDL/CWL/Nextflow file) and semantic version string
- **Version aliases**: Mark specific versions as `production` or `development` — like AWS Lambda aliases
- **Cross-platform registration**: Register a specific workflow version on multiple execution engines (Arvados, SevenBridges, AWS Batch, etc.)
- **Execution provenance**: Record workflow runs with engine-specific run IDs and key-value attributes for file/QC provenance tracking
- **Provenance**: All entities track `created_at` and `created_by` for audit trails

## Architecture

### Entity Relationship Diagram

```mermaid
erDiagram
    Workflow ||--o{ WorkflowVersion : has_versions
    Workflow ||--o{ WorkflowAttribute : has_attributes
    Workflow ||--o{ WorkflowVersionAlias : has_aliases
    WorkflowVersionAlias }o--|| WorkflowVersion : points_to
    WorkflowVersion ||--o{ WorkflowRegistration : registered_on
    WorkflowVersion ||--o{ WorkflowRun : executed_as
    Platform ||--o{ WorkflowRegistration : engine_FK
    Platform ||--o{ WorkflowRun : engine_FK
    WorkflowRun ||--o{ WorkflowRunAttribute : has_attributes

    Platform {
        string name PK
    }

    Workflow {
        uuid id PK
        string name
        datetime created_at
        string created_by
    }

    WorkflowAttribute {
        uuid id PK
        uuid workflow_id FK
        string key
        string value
    }

    WorkflowVersion {
        uuid id PK
        uuid workflow_id FK
        string version
        string definition_uri
        datetime created_at
        string created_by
    }

    WorkflowVersionAlias {
        uuid id PK
        uuid workflow_id FK
        enum alias
        uuid workflow_version_id FK
        datetime created_at
        string created_by
    }

    WorkflowRegistration {
        uuid id PK
        uuid workflow_version_id FK
        string engine FK
        string external_id
        datetime created_at
        string created_by
    }

    WorkflowRun {
        uuid id PK
        uuid workflow_version_id FK
        string engine FK
        string external_run_id
        datetime created_at
        string created_by
    }

    WorkflowRunAttribute {
        uuid id PK
        uuid workflow_run_id FK
        string key
        string value
    }
```

### Design Decisions

**Why separate Workflow and WorkflowVersion?**

A workflow definition evolves over time. The `Workflow` table captures the logical identity (e.g., "Alignment") while `WorkflowVersion` captures each revision with its own version string and definition URI. This means:

- Creating a new version doesn't create a new workflow — it adds a row to `WorkflowVersion`
- All runs across all versions of the same workflow are aggregable via `WorkflowVersion.workflow_id`
- Pipelines reference the logical workflow, not a specific version

**Why a separate alias table?**

Aliases like `production` and `development` let teams mark which version should be used without hardcoding version strings. The `WorkflowVersionAlias` table uses a fixed enum (`production`, `development`) with a `UNIQUE(workflow_id, alias)` constraint — each workflow can have at most one production pointer and one development pointer. Moving an alias is an upsert, providing an audit trail of who changed it and when.

**Why do WorkflowRegistration and WorkflowRun point to WorkflowVersion?**

You register and execute a *specific version* of a workflow. Different versions may have different external IDs on the same platform. The FK to `workflowversion.id` captures this precisely. You can still navigate to the parent workflow via `WorkflowVersion.workflow_id`.

**Why separate WorkflowRun from BatchJob?**

`WorkflowRun` tracks the execution of a workflow version at the domain level, while `BatchJob` tracks infrastructure-level job submission (AWS Batch). A single `WorkflowRun` might correspond to a `BatchJob`, or it might be tracked externally (e.g., in Arvados). This separation keeps the domain model clean.

## Database Models

### Workflow

The core identity entity. Represents a platform-agnostic workflow.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `name` | string | yes | Human-readable workflow name |
| `created_at` | datetime | auto | UTC timestamp of creation |
| `created_by` | string | yes | Username of the creator |

### WorkflowAttribute

Key-value metadata for workflows. Extensible without schema changes.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `workflow_id` | UUID | yes | FK → `workflow.id` |
| `key` | string | yes | Attribute name |
| `value` | string | yes | Attribute value |

### WorkflowVersion

A versioned definition of a workflow.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `workflow_id` | UUID | yes | FK → `workflow.id` |
| `version` | string | yes | Semantic version string (e.g., `"2.1.0"`) |
| `definition_uri` | string | yes | URI to the workflow definition file (WDL, CWL, Nextflow, etc.) |
| `created_at` | datetime | auto | UTC timestamp |
| `created_by` | string | yes | Username of the creator |

**Constraints:** `UNIQUE(workflow_id, version)` — no duplicate version strings per workflow.

### WorkflowVersionAlias

Named pointer to a specific workflow version.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `workflow_id` | UUID | yes | FK → `workflow.id` — scopes the alias |
| `alias` | enum | yes | Fixed enum: `production` or `development` |
| `workflow_version_id` | UUID | yes | FK → `workflowversion.id` |
| `created_at` | datetime | auto | UTC timestamp |
| `created_by` | string | yes | Username who set the alias |

**Constraints:** `UNIQUE(workflow_id, alias)` — one alias pointer per workflow per alias type.

### Platform

A registered workflow execution engine. Single-column reference table — the `name` is the PK. Must be created before workflows can be registered or run on a given engine.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Primary key — e.g., `"Arvados"`, `"SevenBridges"` |

### WorkflowRegistration

Platform-specific registration of a workflow version. The `engine` column is a FK to `platform.name`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `workflow_version_id` | UUID | yes | FK → `workflowversion.id` |
| `engine` | string | yes | FK → `platform.name` |
| `external_id` | string | yes | Workflow identifier on the external platform |
| `created_at` | datetime | auto | UTC timestamp of creation |
| `created_by` | string | yes | Username of the creator |

**Constraints:** `UNIQUE(workflow_version_id, engine)` — one registration per engine per version.

### WorkflowRun

Provenance record linking a workflow version to an external execution. The `engine` column is a FK to `platform.name`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `workflow_version_id` | UUID | yes | FK → `workflowversion.id` |
| `engine` | string | yes | FK → `platform.name` |
| `external_run_id` | string | yes | External run/job ID on the platform |
| `created_at` | datetime | auto | UTC timestamp of creation |
| `created_by` | string | yes | Username of the creator |

### WorkflowRunAttribute

Key-value metadata for workflow runs (e.g., input parameters, output paths).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `workflow_run_id` | UUID | yes | FK → `workflowrun.id` |
| `key` | string | yes | Attribute name |
| `value` | string | yes | Attribute value |

## API Endpoints

All workflow endpoints require authentication. The authenticated user's username is recorded as `created_by`.

### Workflow CRUD

#### Create a Workflow

```
POST /workflows
```

**Request Body:**

```json
{
  "name": "variant-calling-wf",
  "attributes": [
    {"key": "category", "value": "genomics"},
    {"key": "author", "value": "bioinformatics-team"}
  ]
}
```

**Response** (`201 Created`):

```json
{
  "id": "a1b2c3d4-...",
  "name": "variant-calling-wf",
  "created_at": "2026-03-01T12:00:00Z",
  "created_by": "jdoe",
  "attributes": [
    {"key": "category", "value": "genomics"},
    {"key": "author", "value": "bioinformatics-team"}
  ],
  "versions": [],
  "aliases": []
}
```

#### List Workflows

```
GET /workflows?page=1&per_page=20&sort_by=name&sort_order=asc
```

Returns a list of workflows with their attributes, version summaries, and aliases.

#### Get Workflow by ID

```
GET /workflows/{workflow_id}
```

Returns a single workflow with attributes, version summaries, and aliases.

### WorkflowVersion Endpoints

#### Create a Version

```
POST /workflows/{workflow_id}/versions
```

**Request Body:**

```json
{
  "version": "2.1.0",
  "definition_uri": "s3://workflows/variant-calling-v2.1.wdl"
}
```

**Response** (`201 Created`):

```json
{
  "id": "v1v2v3v4-...",
  "workflow_id": "a1b2c3d4-...",
  "version": "2.1.0",
  "definition_uri": "s3://workflows/variant-calling-v2.1.wdl",
  "created_at": "2026-03-01T12:05:00Z",
  "created_by": "jdoe",
  "registrations": []
}
```

**Errors:**
- `404 Not Found` — Workflow does not exist.
- `409 Conflict` — Version string already exists for this workflow.

#### List Versions

```
GET /workflows/{workflow_id}/versions
```

Returns all versions of a workflow, ordered by creation date (newest first).

#### Get Version by ID

```
GET /workflows/{workflow_id}/versions/{version_id}
```

Returns a single version with its registrations.

### WorkflowVersionAlias Endpoints

#### Set/Update an Alias

```
PUT /workflows/{workflow_id}/aliases/{alias}
```

Where `{alias}` is `production` or `development`.

**Request Body:**

```json
{
  "workflow_version_id": "v1v2v3v4-..."
}
```

**Response** (`200 OK`):

```json
{
  "id": "...",
  "workflow_id": "a1b2c3d4-...",
  "alias": "production",
  "workflow_version_id": "v1v2v3v4-...",
  "version": "2.1.0",
  "created_at": "2026-03-01T12:10:00Z",
  "created_by": "jdoe"
}
```

Moving an alias (e.g., changing production from v2.0 to v2.1) is an upsert — same endpoint, new version ID.

**Errors:**
- `404 Not Found` — Workflow or version not found.
- `422 Unprocessable Content` — Invalid alias value.

#### List Aliases

```
GET /workflows/{workflow_id}/aliases
```

Returns all aliases for a workflow.

#### Delete Alias

```
DELETE /workflows/{workflow_id}/aliases/{alias}
```

**Response:** `204 No Content`

### WorkflowRegistration Endpoints

Registrations are nested under a specific version.

#### Register Version on Platform

```
POST /workflows/{workflow_id}/versions/{version_id}/registrations
```

**Request Body:**

```json
{
  "engine": "Arvados",
  "external_id": "zzzzz-7fd4e-abc123def456"
}
```

> **Note:** The `engine` value must match a registered Platform `name`. Create platforms first via `POST /platforms`.

**Response** (`201 Created`):

```json
{
  "id": "...",
  "workflow_version_id": "v1v2v3v4-...",
  "engine": "Arvados",
  "external_id": "zzzzz-7fd4e-abc123def456",
  "created_at": "2026-03-01T12:05:00Z",
  "created_by": "jdoe"
}
```

**Errors:**
- `400 Bad Request` — Engine is not a registered platform.
- `409 Conflict` — A registration for the same engine already exists for this version.

#### List Registrations

```
GET /workflows/{workflow_id}/versions/{version_id}/registrations
```

Returns all platform registrations for a version.

#### Delete Registration

```
DELETE /workflows/{workflow_id}/versions/{version_id}/registrations/{registration_id}
```

**Response:** `204 No Content`

### WorkflowRun Endpoints

#### Create a Run

```
POST /workflows/{workflow_id}/runs
```

**Request Body:**

```json
{
  "workflow_version_id": "v1v2v3v4-...",
  "engine": "Arvados",
  "external_run_id": "zzzzz-xvhdp-run123",
  "attributes": [
    {"key": "sample_id", "value": "sample-001"},
    {"key": "input_bam", "value": "s3://data/sample-001.bam"}
  ]
}
```

**Response** (`201 Created`):

```json
{
  "id": "...",
  "workflow_version_id": "v1v2v3v4-...",
  "workflow_name": "variant-calling-wf",
  "workflow_version": "2.1.0",
  "engine": "Arvados",
  "external_run_id": "zzzzz-xvhdp-run123",
  "created_at": "2026-03-01T14:00:00Z",
  "created_by": "jdoe",
  "attributes": [
    {"key": "sample_id", "value": "sample-001"},
    {"key": "input_bam", "value": "s3://data/sample-001.bam"}
  ]
}
```

#### List Runs (Paginated)

```
GET /workflows/{workflow_id}/runs?page=1&per_page=20&sort_by=created_at&sort_order=desc
```

Lists runs across all versions of the workflow.

**Response:**

```json
{
  "data": [ ... ],
  "total_items": 42,
  "total_pages": 3,
  "current_page": 1,
  "per_page": 20,
  "has_next": true,
  "has_prev": false
}
```

#### Get Run by ID

```
GET /workflow-runs/{run_id}
```

Note: This uses a top-level `/workflow-runs` path (not nested under a workflow) for convenience.

## Source Files

| File | Description |
|------|-------------|
| `api/platforms/models.py` | Platform table model and schemas |
| `api/platforms/services.py` | Platform CRUD services |
| `api/platforms/routes.py` | Platform endpoint handlers |
| `api/workflow/models.py` | Workflow/Version/Alias/Registration/Run table definitions and schemas |
| `api/workflow/services.py` | Workflow business logic (create, list, version/alias CRUD, engine validation) |
| `api/workflow/routes.py` | Workflow endpoint handlers |
| `tests/api/test_platforms.py` | Platform CRUD tests |
| `tests/api/test_workflows.py` | Workflow CRUD tests |
| `tests/api/test_workflow_versions.py` | Version CRUD tests |
| `tests/api/test_workflow_aliases.py` | Alias CRUD tests |
| `tests/api/test_workflow_registrations.py` | Registration endpoint tests (incl. engine validation) |
| `tests/api/test_workflow_runs.py` | Workflow run endpoint tests (incl. engine validation) |
