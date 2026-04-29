# Platform / WorkflowDeployment / WorkflowRun Relationship Analysis

**Date**: 2026-03-24
**Decision**: Keep status quo (Option A)

## Context

We evaluated whether the `Platform` table should be removed and whether `WorkflowRun` should FK to `WorkflowDeployment` instead of independently carrying `workflow_version_id` + `engine`.

## Current State

### Entities

- **Platform** (`api/platforms/models.py:11`) — single-column table (`name` PK). Own CRUD endpoints (`POST/GET/GET-by-name`). Used solely as an FK target for `WorkflowDeployment.engine` and `WorkflowRun.engine`.

- **WorkflowDeployment** (`api/workflow/models.py:96`) — links `workflow_version_id` + `engine` + `external_id`. Unique constraint `(workflow_version_id, engine)`. **Nothing FKs to it** — it's a leaf/audit record.

- **WorkflowRun** (`api/workflow/models.py:127`) — links `workflow_version_id` + `engine` + `external_run_id`. **Many things FK to it**: `QCRecord.workflow_run_id`, `QCMetric.workflow_run_id`, `FileWorkflowRun.workflow_run_id`.

### Key Observation

Both `WorkflowDeployment` and `WorkflowRun` independently carry `workflow_version_id` and `engine`. There is **no FK relationship between them** — a run doesn't know which deployment it came from.

### Platform's Other Usage

The `ActionPlatform` enum in the actions/pipelines system (`api/actions/models.py:17`) is a **separate concept** — a hardcoded Python enum (`Arvados`, `SevenBridges`), not backed by the `Platform` table.

## Options Evaluated

```mermaid
graph TD
    subgraph Option A: Status Quo
        A_P[Platform] -->|FK| A_D[WorkflowDeployment]
        A_P -->|FK| A_R[WorkflowRun]
        A_V[WorkflowVersion] -->|FK| A_D
        A_V -->|FK| A_R
    end

    subgraph Option B: Run points to Deployment
        B_V[WorkflowVersion] -->|FK| B_D[WorkflowDeployment]
        B_D -->|FK| B_R[WorkflowRun]
    end

    subgraph Option C: Drop Platform, keep engine as string
        C_V2[WorkflowVersion] -->|FK| C_D2[WorkflowDeployment]
        C_V2 -->|FK| C_R2[WorkflowRun]
    end
```

### Option A: Status Quo (Platform + independent engine FKs) ← CHOSEN

| | |
|---|---|
| **Pros** | Platform table provides a controlled vocabulary for engine names; typos are caught at insert time. Runs and deployments are loosely coupled — you can record a run without ever creating a deployment. |
| **Cons** | Platform is a single-column table that's essentially a glorified enum. Two-step ceremony to onboard a new engine (`POST /platforms` first). Deployment is a dangling record — nothing references it, so there's no structural guarantee that runs relate to known deployments. Engine string is duplicated across Deployment and Run with no cross-validation. |

### Option B: Remove Platform, WorkflowRun FKs to WorkflowDeployment

| | |
|---|---|
| **Pros** | **Strongest provenance chain**: Run → Deployment → Version → Workflow. One FK on Run gives you the version, the platform, and the external workflow ID. Eliminates the redundant `engine` + `workflow_version_id` duplication on Run. Makes Deployment structurally meaningful instead of an orphan record. Answers the question "which runs used this deployment?" via a simple reverse FK query. |
| **Cons** | **Every run requires a deployment record first** — no recording ad-hoc runs on a platform where the workflow wasn't formally "deployed." This is a constraint that may or may not match reality. If a workflow is deployed once but run 10,000 times, you still just have one deployment row, so cardinality is fine — but if you need to run something on a platform without bothering to register the deployment, this blocks you. Removes `engine` from Run's top-level columns, making "list all runs on Arvados" a join instead of a `WHERE`. Migration is non-trivial: need to match existing runs to deployments (or create deployments retroactively). |

### Option C: Drop Platform table, keep `engine` as a plain string on both

| | |
|---|---|
| **Pros** | Simplest change — just remove the FK constraints and the Platform table/endpoints. No ceremony to onboard new engines. Engine is still a first-class column on both Deployment and Run for easy filtering. Low migration risk. |
| **Cons** | No controlled vocabulary — freeform strings mean `"arvados"` vs `"Arvados"` vs `"ARVADOS"` are all different values. Loses the ability to list "all known platforms" from the database. Deployment remains a disconnected record. |

### Hybrid (not chosen, but noted for reference)

Keep Deployment as-is but make it *optional* on Run. Add a nullable `workflow_deployment_id` FK on `WorkflowRun` while keeping `engine` as a plain string. This gives the provenance link when available without blocking run creation when it isn't.

## Decision Rationale

Keeping the status quo because:

1. The Platform table provides useful controlled vocabulary at low cost
2. The flexibility to record runs without prior deployments matches real-world usage patterns
3. No migration churn for a change that doesn't address an immediate pain point

## Future Considerations

- If we find that runs should always trace back to a specific deployment, Option B becomes the right model
- If the Platform table ceremony becomes annoying, Option C is a quick simplification
- The hybrid approach is available as a middle ground if needed
