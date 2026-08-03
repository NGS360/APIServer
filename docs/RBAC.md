# Role-Based Access Control

This document specifies the requirements and design for role-based access control (RBAC) in the NGS360 API, covering the permission model, its enforcement, and the phased rollout required to introduce it without breaking existing consumers.

## Overview

NGS360 today has authentication but effectively no authorization. RBAC provides:

- **Least privilege**: A closed catalog of `resource:action` permissions, grouped into named roles, replacing the single `is_superuser` boolean
- **Two grant scopes**: Global roles for platform resources (runs, workflows, vendors, settings) and per-project roles for project-owned data (samples, QC records, files)
- **Auditable grants**: Every assignment records who granted it, when, and by what mechanism
- **A safe rollout path**: A dry-run mode that logs denials without enforcing them, so the permission model can be validated against real production traffic before it starts rejecting requests
- **Machine identities**: First-class service accounts with narrowly scoped API keys, replacing the current practice of integrations borrowing a human's credentials

### Current state

The measurements below are the baseline this design is written against. Regenerate them before implementation begins; the counts are current as of this document.

| Metric | Value |
|--------|-------|
| Total API routes | 116 (111 feature routes + 5 OAuth) |
| Routes with **no** authentication | 85 |
| — of those, legitimately public (login, register, password reset, OAuth handshake) | 11 |
| — **routes that must be closed** | **74** |
| Routes gated by `is_superuser` | 3 |
| Distinct permissions today | 1 (`users.is_superuser`) |
| Membership / role / permission tables | 0 |

Routers with **zero** authentication references: `actions` (5 routes), `jobs` (6), `manifest` (3), `platforms` (3), `samples` (3), `search` (1), `settings` (3), `vendors` (5). Partially open: `runs` (13/16 open), `project` (9/16), `workflow` (9/13), `files` (7/9), `qcmetrics` (4/5), `pipeline` (3/5).

The three `is_superuser`-gated routes are `DELETE /projects/{project_id}/samples/{sample_id}` (`api/project/routes.py:400`), `PATCH /files/{file_id}` (`api/files/routes.py:264`), and `DELETE /files/{file_id}` (`api/files/routes.py:290`).

> **Immediate hazard, independent of this design.** `PUT /api/v1/settings/{key}` is unauthenticated in production. It writes `DATA_BUCKET_URI`, `RESULTS_BUCKET_URI`, `DEMUX_WORKFLOW_CONFIGS_BUCKET_URI`, and `MANIFEST_VALIDATION_LAMBDA` — the values that determine where the platform reads and writes data and which Lambda it invokes. If Phase 1b (below) is more than roughly two weeks out, close this route as a standalone hotfix rather than waiting for the rollout.

## Architecture

### The three grant planes

Authorization is **grant-only**: a permission is either granted by some plane or it is denied. There are no deny rules.

| Plane | Carrier | Applies to |
|-------|---------|------------|
| Break-glass | `users.is_superuser` | Everything; short-circuits ahead of all role evaluation |
| Global | `user_role` — additive, a user may hold several | Platform resources, and project-scopable permissions across *all* projects |
| Project | `project_member` — exactly one role per user per project | That project's data only |

Both planes draw on **one shared permission vocabulary**. The permission string is scope-agnostic; the *grant* carries the scope. `sample:create` held via a global role means "in any project"; held via a project role it means "in this project". This avoids maintaining a parallel `project_sample:*` vocabulary and makes moving a permission between planes a policy decision rather than a code change.

### Entity Relationship Diagram

```mermaid
erDiagram
    User ||--o{ UserRole : "holds (global)"
    User ||--o{ ProjectMember : "member of"
    Role ||--o{ UserRole : "granted as"
    Role ||--o{ ProjectMember : "granted as"
    Role ||--o{ RolePermission : "grants"
    Project ||--o{ ProjectMember : "has members"

    User {
        uuid id PK
        string username UK
        string email UK
        boolean is_active
        boolean is_verified
        boolean is_superuser
    }

    Project {
        uuid id PK
        string project_id UK
        string created_by
    }

    Role {
        uuid id PK
        string name UK
        string display_name
        string description
        string scope
        boolean is_builtin
        datetime created_at
        datetime updated_at
    }

    RolePermission {
        uuid id PK
        uuid role_id FK
        string permission
    }

    UserRole {
        uuid id PK
        uuid user_id FK
        uuid role_id FK
        string source
        uuid granted_by FK
        datetime granted_at
    }

    ProjectMember {
        uuid id PK
        uuid project_id FK
        uuid user_id FK
        uuid role_id FK
        string source
        uuid granted_by FK
        datetime granted_at
    }
```

### Design Decisions

**Why are permissions defined in code, not in a database table?**

The permission catalog is a closed `StrEnum` in `api/rbac/permissions.py`. Roles are database rows; permissions are not.

A permission only means something if some route calls `require_permission()` with it. A `permission` table therefore cannot describe capability — it can only describe intent, and an admin who invents `project:archive` in the table gets a permission that silently does nothing forever. Conversely, a typo in a code-level check (`require_permission("settings:update")` against a catalog entry of `setting:update`) makes a route permanently unreachable with no error anywhere; as an enum member, the same typo fails at import.

The editability people actually want is **role** editability, and that is fully preserved: roles are rows, `role_permission` is a table, and admins compose arbitrary custom roles from the catalog through the API.

**Why no wildcards?**

Wildcards are permitted when *defining* a role in code (`ALL_PERMISSIONS = frozenset(Permission)`) and never evaluated at check time. A role holding `workflow:*` silently acquires `workflow:purge` the day someone adds it — a role gaining a permission with nobody deciding. With enumerated permissions, widening a role requires editing `ROLE_DEFINITIONS`, which appears in code review. Checks are also O(1) set membership rather than glob matching per request.

**Why grant-only, with no deny rules?**

Deny rules require a precedence lattice, and once one exists, answering "why can this user do X?" means evaluating the whole rule set rather than taking a set union. Every requirement encountered here ("this user must not see project P") is expressible by not granting. Account-level suspension is already handled by `is_active` / `is_verified` in `get_current_active_user`.

**Why does a global role grant access to all projects?**

Because the data model forces it. Three cases have no path to a project:

- `SequencingRun` reaches projects only through `SampleSequencingRun → Sample → Project`, many-to-many. A single flowcell legitimately spans projects, so a demux operator cannot be a member of every project on it.
- `BatchJob` has no project column at all — only `user: str` and a free-text `command`.
- The pipeline writeback path (`POST /qcmetrics`, `POST /files`) runs as a service account that cannot be enrolled in every project whose results it writes.

Without a global escape hatch, either demultiplexing breaks or the service account gets auto-enrolled in every project — a worse, less auditable version of the same grant. So global roles *may* carry project-scopable permissions, and when they do they apply everywhere. Permissions marked global-only are rejected from project roles at role-creation time.

**Why does `member` ship able to read every project?**

The default role holds *global* `project:read`, `sample:read`, `qcrecord:read`, `file:read`, and `file:download`. This deliberately preserves today's "any authenticated user can read anything" behaviour while writes become membership-gated.

The alternative — shipping read isolation and enforcement together — means one change that both rejects writes and empties every list view, with no way to separate the two if something goes wrong. Instead, tightening reads later is a **role edit through the admin API**: remove those five permissions from `member`. No deploy, no config flag, no second code path to test, and reversible in one API call. This is the primary reason the design allows global roles to carry project-scopable permissions.

**Why does `project_member` reference `project.id` and not `project.project_id`?**

`Project` carries both a UUID surrogate key (`id`) and a string business key (`project_id`, e.g. `P-20260731-0001`), and existing foreign keys are split between them: `Sample.project_id` and `QCRecordMetadata.project_id` reference the string, while `FileProject.project_id` — the most recently added join table — references the UUID.

Membership uses the UUID:

- `get_validated_project` already loads the entire `Project` row before any permission check runs, so `project.id` is in hand at zero cost. Using the string key saves no lookup.
- `project_id` is user-visible and will eventually be renamed. A rename would either be rejected by the foreign key or cascade through it — either way, someone is debugging authorization during a rename.
- Authorization tables should reference immutable surrogate keys.

The consequence to design around: the permission dependency must run *after* `get_validated_project`. FastAPI's dependency graph handles this automatically because `require_project_permission` declares `ProjectDep` as a sub-dependency.

**Why two assignment tables instead of one polymorphic `role_assignment`?**

A single `role_assignment(user_id, role_id, scope_type, scope_id)` table generalizes to future scope types, but cannot carry a real foreign key to `project`, invites `scope_type` string typos, and needs a partial unique index that MySQL does not support. Separately, "who is on this project" is a product concept with a UI screen behind it, not merely an authorization artifact. Two tables.

**Why are global grants additive but project grants exclusive?**

Global roles compose meaningfully — `member` plus `service_account` is a legitimate combination. The three project roles are a total order (`project_viewer` ⊂ `project_contributor` ⊂ `project_owner`), so stacking them adds nothing but ambiguity in the UI. Hence `UNIQUE(project_id, user_id)`. If additive project roles are ever needed, relaxing the constraint to `UNIQUE(project_id, user_id, role_id)` requires no resolver changes — it already unions.

**A note on naming.** The schema already uses `role` as a column name with an unrelated meaning: `FileProject.role` holds values like `"samplesheet"`, and `FileSample.role` holds `"tumor"` / `"normal"`. Throughout this design, an RBAC role is always the `role` table or a `role_id` column. The existing columns are untouched.

## Permission Catalog

57 permissions across 18 resources. **Scope** is `G` for global-only (may not appear in a project role) or `P` for project-scopable (may appear in either plane). **Risk** indicates blast radius, for the benefit of anyone composing a custom role.

### Project-owned data

| Permission | Scope | Risk | Routes |
|------------|-------|------|--------|
| `project:read` | P | low | `GET /projects`, `/projects/{id}`, `/projects/search`, `/projects/attributes` |
| `project:create` | G | low | `POST /projects` |
| `project:update` | P | low | `PUT /projects/{id}`, `PATCH /projects/{id}` |
| `project:delete` | P | high | *reserved — no route today* |
| `project:manage_members` | P | medium | `GET/POST/PATCH/DELETE /projects/{id}/members` (new) |
| `project:submit_action` | P | **high** | `POST /projects/{id}/actions/submit` — spends AWS Batch |
| `project:ingest` | P | **high** | `POST /projects/{id}/ingest` — spends AWS Batch, writes S3 |
| `sample:read` | P | low | `GET /projects/{id}/samples`, `GET/POST /samples/search` |
| `sample:create` | P | low | `POST /projects/{id}/samples`, `/samples/upload`, `/samples/bulk` |
| `sample:update` | P | low | `PUT /projects/{id}/samples/{sample_id}` |
| `sample:delete` | P | medium | `DELETE /projects/{id}/samples/{sample_id}` |
| `qcrecord:read` | P | low | `GET /qcmetrics/{id}`, `GET/POST /qcmetrics/search` |
| `qcrecord:create` | P | low | `POST /qcmetrics` |
| `qcrecord:delete` | P | medium | `DELETE /qcmetrics/{id}` |
| `file:read` | P | low | `GET /files`, `/files/{id}`, `/files/{id}/versions` |
| `file:download` | P | medium | `GET /files/download` |
| `file:create` | P | low | `POST /files`, `POST /files/upload` |
| `file:update` | P | low | `PATCH /files/{id}` |
| `file:delete` | P | high | `DELETE /files/{id}` |

### Platform resources

These have no path to a project (see *Design Decisions*), so they are global-only.

| Permission | Scope | Risk | Routes |
|------------|-------|------|--------|
| `run:read` | G | low | `GET /runs`, `/runs/search`, `/runs/{id}`, `/{id}/samplesheet`, `/{id}/metrics`, `/{id}/samples`, `/runs/demultiplex`, `/runs/demultiplex/{workflow_id}` |
| `run:create` | G | low | `POST /runs` |
| `run:update` | G | medium | `PUT /runs/{id}`, `POST /runs/{id}/samplesheet` |
| `run:associate` | G | medium | `POST /runs/{id}/samples`, `DELETE /runs/{id}/samples`, `DELETE /runs/{id}/samples/{sample_id}` |
| `run:demux` | G | **high** | `POST /runs/demultiplex` — spends compute, deletes run-scoped QC records |
| `job:read` | G | low | `GET /jobs` (filtered to own), `/jobs/{id}`, `/{id}/log`, `/{id}/log/paginated` |
| `job:read_all` | G | medium | Removes the "own jobs" filter from `GET /jobs` |
| `job:submit` | G | **high** | `POST /jobs` |
| `job:update` | G | medium | `PUT /jobs/{id}` — status writeback; service accounts only |
| `workflow:read` | G | low | All `GET /workflows/...` |
| `workflow:create` | G | medium | `POST /workflows`, `POST /workflows/{id}/versions` |
| `workflow:update` | G | **high** | `PUT /workflows/{id}/aliases/{alias}` — repointing `production` changes what executes |
| `workflow:delete` | G | medium | `DELETE /workflows/{id}/aliases/{alias}` |
| `workflow:deploy` | G | high | `POST` / `DELETE .../deployments` |
| `pipeline:read` | G | low | `GET /pipelines`, `/pipelines/{id}` |
| `pipeline:create` | G | low | `POST /pipelines` |
| `pipeline:update` | G | medium | `POST` / `DELETE /pipelines/{id}/workflows/...` |
| `platform:read` | G | low | `GET /platforms`, `/platforms/{name}` |
| `platform:create` | G | medium | `POST /platforms` |
| `vendor:read` | G | low | `GET /vendors`, `/vendors/{id}` |
| `vendor:create` | G | low | `POST /vendors` |
| `vendor:update` | G | low | `PUT /vendors/{id}` |
| `vendor:delete` | G | medium | `DELETE /vendors/{id}` |
| `setting:read` | G | medium | `GET /settings`, `GET /settings/{key}` |
| `setting:update` | G | **critical** | `PUT /settings/{key}` — controls bucket URIs and the validation Lambda ARN |

### Cross-cutting and infrastructure

| Permission | Scope | Risk | Routes |
|------------|-------|------|--------|
| `manifest:read` | G | medium | `GET /manifest` — accepts an arbitrary S3 prefix |
| `manifest:upload` | G | **high** | `POST /manifest` — arbitrary S3 write |
| `manifest:validate` | G | medium | `POST /manifest/validate` |
| `file:browse` | G | **high** | `GET /files/list` — arbitrary S3 prefix listing |
| `action:read` | G | low | `GET /actions/configs`, `/options`, `/platforms`, `/types` |
| `action:validate` | G | low | `POST /actions/config/validate` |
| `search:query` | G | low | `GET /search` and the `*/search` read endpoints |
| `chat:use` | G | medium | `POST /chat`, `/chat/stream`, `GET /chat/threads/{id}` |
| `user:read` | G | low | `GET /users/search` |
| `user:manage` | G | **high** | New admin user endpoints (activate, verify, set superuser) |
| `role:read` | G | low | `GET /rbac/permissions`, `/rbac/roles`, `/rbac/users/{u}/roles` |
| `role:manage` | G | **critical** | `POST` / `PATCH` / `DELETE /rbac/roles`, global role grant and revoke |
| `system:reindex` | G | high | `POST /projects/search`, `POST /runs/search`, `POST /qcmetrics/search`, `POST /samples/reindex` |

**`manifest:*` and `file:browse` are deliberately global-only.** Those endpoints accept an arbitrary S3 URI, so they cannot be project-scoped without a URI-to-project resolver, which does not exist. This is a known gap, listed under *Non-Goals*.

**Note the reindex route shapes.** `POST /projects/search`, `POST /runs/search`, and `POST /qcmetrics/search` trigger *reindexing*, not searching — the read counterparts are the `GET` verbs on the same paths. `POST /samples/reindex` is named consistently. All four map to `system:reindex`, not to `search:query`.

### Catalog definition

```python
# api/rbac/permissions.py
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Permission(StrEnum):
    PROJECT_READ = "project:read"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    PROJECT_MANAGE_MEMBERS = "project:manage_members"
    PROJECT_SUBMIT_ACTION = "project:submit_action"
    PROJECT_INGEST = "project:ingest"
    SAMPLE_READ = "sample:read"
    # ... 57 members total


Risk = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    resource: str
    description: str
    project_scopable: bool
    risk: Risk


CATALOG: dict[Permission, PermissionSpec] = {
    Permission.PROJECT_READ: PermissionSpec(
        "project", "View project metadata and attributes", True, "low"),
    Permission.SETTING_UPDATE: PermissionSpec(
        "setting", "Change platform settings (bucket URIs, Lambda ARNs)", False, "critical"),
    # ...
}

PROJECT_SCOPABLE = frozenset(p for p, s in CATALOG.items() if s.project_scopable)
ALL_PERMISSIONS = frozenset(Permission)
```

A unit test asserting `set(CATALOG) == set(Permission)` prevents the enum and the metadata from drifting apart.

## Role Catalog

Roles are database rows so that administrators can compose custom ones. The **builtin** roles listed here have their permission sets declared in code (`api/rbac/roles.py`) and re-derived on each deploy, so adding a permission to a builtin role is a reviewable code change.

### Global roles

| Role | Purpose | Permissions |
|------|---------|-------------|
| `member` | Default for every authenticated user | `action:read`, `platform:read`, `vendor:read`, `workflow:read`, `pipeline:read`, `run:read`, `job:read`, `job:submit`, `setting:read`, `search:query`, `chat:use`, `user:read`, `project:create`, plus the transitional global reads: `project:read`, `sample:read`, `qcrecord:read`, `file:read`, `file:download` |
| `lab_manager` | Sequencing core — registers runs, demultiplexes, ingests vendor deliveries | `member` + `run:create`, `run:update`, `run:associate`, `run:demux`, `manifest:read`, `manifest:upload`, `manifest:validate`, `file:browse`, `file:create`, `file:update`, `sample:create`, `sample:update`, `qcrecord:create`, `project:ingest`, `job:read_all` |
| `platform_admin` | Owns the executable catalog and platform configuration | `member` + `platform:create`, `vendor:create`, `vendor:update`, `vendor:delete`, `workflow:create`, `workflow:update`, `workflow:delete`, `workflow:deploy`, `pipeline:create`, `pipeline:update`, `action:validate`, `setting:update`, `system:reindex`, `job:read_all`, `job:update` |
| `service_account` | Machine writeback — pipelines, the Batch status poller, MCP | `project:read`, `run:read`, `run:update`, `sample:read`, `sample:create`, `qcrecord:create`, `file:create`, `file:update`, `job:read_all`, `job:update` |
| `auditor` | Compliance, QA, read-only agents | Every `*:read` permission, plus `file:download`, `search:query`, `role:read` |
| `admin` | Platform administrator | `ALL_PERMISSIONS`, recomputed at each sync so new permissions are picked up automatically |

### Project roles

| Role | Permissions |
|------|-------------|
| `project_viewer` | `project:read`, `sample:read`, `qcrecord:read`, `file:read`, `file:download` |
| `project_contributor` | `project_viewer` + `project:update`, `sample:create`, `sample:update`, `sample:delete`, `qcrecord:create`, `qcrecord:delete`, `file:create`, `file:update`, `file:delete`, `project:submit_action`, `project:ingest` |
| `project_owner` | `project_contributor` + `project:manage_members`, `project:delete` |

### Why this set, and how to evaluate additions

`member` plus `admin` alone would reproduce today's problem with extra steps: every run registration, workflow alias change, and settings edit funnelling through the same two people. `service_account` must be separate from any human role because it needs `job:update` — the ability to write another user's job status, which no human role should hold and which cannot be expressed as "the owner can update it", since the AWS Batch poller is not the owner.

The rule for future requests: **a new global role is justified only if it adds a write permission on a global (non-project) resource.** Personas that differ only in *which projects* they touch — bioinformatician, PI, sequencing tech, external collaborator — are already expressed by project membership. Adding a global role per persona would re-implement project scoping in the global plane, which is exactly what this design avoids. Requests like "contributor without delete" are real, and they are served by custom roles, which is the reason roles are database rows.

The three project roles are the minimum lattice separating *see*, *change*, and *control who sees and changes*. Fewer collapses two of those; more is site policy rather than platform policy.

## Database Schema

Four new tables in `api/rbac/models.py`. All primary and foreign keys are `sa.Uuid()`, matching the existing schema. New model modules **must** be added to the import block in `alembic/env.py`, or autogenerate will propose dropping these tables.

### role

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `name` | string(64) | yes | Stable identifier, e.g. `project_owner` |
| `display_name` | string(128) | yes | Human-readable label for the UI |
| `description` | string(512) | no | What the role is for |
| `scope` | enum | yes | `global` or `project` |
| `is_builtin` | boolean | auto | Seeded role; cannot be renamed or deleted, and its permission set is re-derived from code on each sync |
| `created_at` | datetime | auto | UTC |
| `updated_at` | datetime | auto | UTC |

**Constraints:** `UNIQUE(name)`, indexed. `scope` indexed.

### role_permission

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `role_id` | UUID | yes | FK → `role.id`, `ON DELETE CASCADE` |
| `permission` | string(64) | yes | Value of a `Permission` enum member |

**Constraints:** `UNIQUE(role_id, permission)` — prevents duplicate grants within a role. `role_id` indexed. Writes validate `permission` against `Permission`, and reject non-`PROJECT_SCOPABLE` permissions on a `scope=project` role, with `422`.

### user_role

Global role grant. Additive — a user may hold several.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `user_id` | UUID | yes | FK → `users.id`, `ON DELETE CASCADE` |
| `role_id` | UUID | yes | FK → `role.id`, `ON DELETE CASCADE` |
| `source` | enum | auto | `manual`, `bootstrap`, `migration`, or `directory` |
| `granted_by` | UUID | no | FK → `users.id`; null for automated grants |
| `granted_at` | datetime | auto | UTC |

**Constraints:** `UNIQUE(user_id, role_id)`. Both FK columns indexed.

### project_member

Project-scoped role grant. Exactly one role per user per project.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | auto | Primary key |
| `project_id` | UUID | yes | FK → `project.id`, `ON DELETE CASCADE` |
| `user_id` | UUID | yes | FK → `users.id`, `ON DELETE CASCADE` |
| `role_id` | UUID | yes | FK → `role.id`, `ON DELETE RESTRICT` — a role in use cannot be deleted |
| `source` | enum | auto | `manual`, `bootstrap`, `migration`, or `directory` |
| `granted_by` | UUID | no | FK → `users.id` |
| `granted_at` | datetime | auto | UTC |

**Constraints:** `UNIQUE(project_id, user_id)` — one role per user per project. `project_id` and `user_id` indexed.

### Why the `source` column ships in v1

Nothing in v1 sets `source` to `directory`. It exists so that a future AD or LDAP group-sync job can reconcile *only the rows it owns*, deleting stale directory-derived grants without touching grants an administrator made by hand. Adding the column later would require a backfill that guesses at provenance it no longer has.

### Index coverage

The two hot queries are `user_role WHERE user_id` (covered by its index) and `project_member WHERE user_id AND project_id` (covered by the unique constraint). The project-visibility query, `project_member WHERE user_id`, is covered by the `user_id` index. No additional indexes are required.

### Schema conventions this design deliberately does not follow

Two inconsistencies exist in the current schema and are **not** propagated:

- `refresh_tokens`, `password_reset_tokens`, and `email_verification_tokens` reference `users.username`, while `oauth_providers` and `api_keys` reference `users.id`. All four new tables reference `users.id`.
- Every business table records its actor as a plain `created_by: str` holding a username, with no foreign key. The new tables use a real `granted_by` FK to `users.id`.

**`users.username` must be treated as immutable.** `UserUpdate` (`api/auth/models.py:202`) currently declares it mutable. No route exposes that today, but if one ever does, a rename would silently orphan every `created_by` string in the schema *and* break the three token tables that reference `users.username`. Renaming must be either removed from the model or implemented as an explicit, fully-cascading operation.

## Resolution Semantics

```
effective(user, permission, project=None) -> bool

  1. user.is_superuser                                    -> ALLOW   (break-glass)
  2. permission in global_permissions(user)               -> ALLOW
  3. project is not None and
     permission in project_permissions(user, project.id)  -> ALLOW
  4. otherwise                                            -> DENY

  global_permissions(user)          = union of role.permissions over user_role(user)
  project_permissions(user, pid)    = permissions of the single role in
                                      project_member(user, pid), or the empty set
```

There is no precedence between the global and project planes because there are no denies — they union. `is_superuser` short-circuits ahead of both.

### Defaults and specific cases

**A user with no roles gets nothing.** Every permission-gated endpoint returns 403. Only the always-open set works: `GET /`, `GET /api/health`, `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, the password-reset and email-verification routes, `GET /auth/oauth/providers`, `/auth/oauth/{provider}/authorize`, `/auth/oauth/{provider}/callback`, `GET /auth/me`, and the caller's own API-key CRUD.

**New users are auto-granted `member`.** A brand-new corporate-SSO user landing on a wall of 403s generates one support ticket per user. The grant happens at both creation sites — `register_user` (`api/auth/services.py`) and `find_or_create_oauth_user` (`api/auth/oauth2_service.py`) — through a single shared `assign_default_roles()`, with the role name read from `DEFAULT_USER_ROLE` (default `member`; empty string disables). `member` is deliberately harmless: it can read catalogs and create its own projects.

**`POST /projects` grants the creator `project_owner` in the same transaction as the project insert.** Without this, a user creates a project they immediately cannot administer. This applies equally to project creation via MCP.

**`is_superuser` remains outside the role system.** It is break-glass: if a bad `role:manage` edit strips `role:manage` from `admin`, superusers are the way back in. It is set only via `BOOTSTRAP_ADMIN_USERNAMES` or an explicit `user:manage` operation, never used for routine access, and `GET /auth/me` surfaces both it and the user's roles so nobody has to wonder why a permission appears to work. Startup logs a warning if the superuser count exceeds a configured threshold.

## Enforcement

### Dependency chain

```
oauth2_scheme
  → get_current_user            (existing: JWT or ngs360_ API key)
  → get_current_active_user     (existing: is_active and is_verified)
  → load_authz                  (new: resolves global permissions once per request)
  → require_permission(...)             (global plane)
  → require_project_permission(...)     (project plane; composes with ProjectDep)
```

Layering *below* `get_current_user` matters: the existing API-key path and the existing test dependency overrides both continue to work untouched. Because `get_current_user` already re-loads the `User` row from the database on every request, roles live in the database with **no JWT format change** — the token stays `{sub, exp, iat, type}` and revocation takes effect immediately.

### The authorization context

```python
# api/rbac/deps.py
@dataclass
class AuthzContext:
    user_id: uuid.UUID
    username: str
    is_superuser: bool
    global_permissions: frozenset[str]
    _session: Session
    _project_cache: dict[uuid.UUID, frozenset[str]] = field(default_factory=dict)

    def has(self, perm: Permission) -> bool:
        """Global-plane check."""
        return self.is_superuser or perm in self.global_permissions

    def has_in_project(self, perm: Permission, project_id: uuid.UUID) -> bool:
        """Global grant OR project-role grant."""
        return self.has(perm) or perm in self._project_permissions(project_id)

    def visible_project_ids(
        self, perm: Permission = Permission.PROJECT_READ
    ) -> set[uuid.UUID] | None:
        """None means unrestricted — the caller must not add a WHERE clause."""
        if self.has(perm):
            return None
        return set(self._session.exec(
            select(ProjectMember.project_id)
            .join(RolePermission, RolePermission.role_id == ProjectMember.role_id)
            .where(ProjectMember.user_id == self.user_id,
                   RolePermission.permission == perm)
        ).all())


AuthzDep = Annotated[AuthzContext, Depends(load_authz)]
```

### The guard factories

```python
def require_permission(*perms: Permission, mode: Literal["all", "any"] = "all"):
    """Global-plane guard. Returns the AuthzContext so routes can reuse it."""
    def _dep(authz: AuthzDep) -> AuthzContext:
        check = all if mode == "all" else any
        if not check(authz.has(p) for p in perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=...)
        return authz
    return _dep


def require_project_permission(*perms: Permission, mode: Literal["all", "any"] = "all"):
    """Project-plane guard. Returns the Project, so it is a drop-in for ProjectDep."""
    def _dep(project: ProjectDep, authz: AuthzDep) -> Project:
        check = all if mode == "all" else any
        if not check(authz.has_in_project(p, project.id) for p in perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=...)
        return project
    return _dep
```

Because `require_project_permission` **returns the `Project`**, every existing `/projects/{project_id}/...` route converts by replacing `ProjectDep` with one annotated alias — the handler body is untouched:

```python
# api/project/routes.py — before
@router.put("/{project_id}")
def update_project(session: SessionDep, project: ProjectDep, body: ProjectUpdate): ...

# after
ProjectWrite = Annotated[Project, Depends(require_project_permission(Permission.PROJECT_UPDATE))]

@router.put("/{project_id}")
def update_project(session: SessionDep, project: ProjectWrite, body: ProjectUpdate): ...
```

For global checks where the handler does not need the context, the dependency goes in the decorator:

```python
# api/settings/routes.py
@router.put("/{key}", dependencies=[Depends(require_permission(Permission.SETTING_UPDATE))])
def update_setting(session: SessionDep, key: str, body: SettingUpdate) -> Setting: ...
```

### Authentication is the default, not an opt-in

Auditing 116 routes by hand will miss one, and every route added afterwards starts life unauthenticated — which is precisely how the current state arose. Instead, authentication is applied at router registration:

```python
# main.py
AUTHENTICATED = [Depends(get_current_active_user)]

for r in (actions_router, chat_router, files_router, jobs_router, manifest_router,
          project_router, qcmetrics_router, runs_router, samples_router, search_router,
          settings_router, vendors_router, workflow_router, pipeline_router,
          platforms_router, users_router):
    app.include_router(r, prefix=API_PREFIX, dependencies=AUTHENTICATED)

# auth_router and oauth_router keep their existing public registration
```

Router-level dependencies are additive and cannot be overridden per route, so only the weakest common requirement — authentication — belongs there; permission checks layer on per route. This closes all 74 open routes in one change and makes "forgot to protect the new route" structurally impossible.

### List endpoints filter rows; they do not return 403

`GET /projects`, `GET /projects/search`, `GET /qcmetrics/search`, `GET /files`, `GET /samples/search`, `GET /jobs`, and `GET /search` must return a *narrower list*, not a denial. This is expressed as a scope dependency yielding plain data, so the service layer keeps its existing convention of receiving primitives rather than `User` objects:

```python
ProjectScopeDep = Annotated[set[uuid.UUID] | None, Depends(project_scope())]

@router.get("")
def get_projects(session: SessionDep, scope: ProjectScopeDep, page: int = 1, ...):
    return services.get_projects(session, visible_project_ids=scope, page=page, ...)
```

```python
# api/project/services.py
def get_projects(session, *, visible_project_ids: set[uuid.UUID] | None = None, ...):
    stmt = select(Project)
    if visible_project_ids is not None:
        if not visible_project_ids:
            return ProjectsPublic(data=[], total_items=0, ...)
        stmt = stmt.where(Project.id.in_(visible_project_ids))
```

**Filtering must happen in the SQL `WHERE` clause, never on the page slice after the fact.** `ProjectsPublic` returns `total_items`, `total_pages`, and `has_next`; post-filtering a page produces pages of 3, 7, and 0 rows at `per_page=20` and a `has_next` that lies. The same applies to `/runs`, `/files`, and `/qcmetrics`.

For `GET /jobs` the analogous filter is on username, since `BatchJob.user` is a username string:

```python
user_filter = None if authz.has(Permission.JOB_READ_ALL) else authz.username
```

### OpenSearch-backed search is a known v1 limitation

`GET /search`, `GET /projects/search`, `GET /runs/search`, `GET /samples/search`, and `GET /qcmetrics/search` query OpenSearch, which knows nothing about `project_member`. The options are to index an ACL field and push a `terms` filter into the query — correct pagination and totals, but requiring a full reindex and making grant changes eventually consistent — or to post-filter hits, which breaks `total` and page sizes.

**v1 decision:** database-backed list endpoints get row filtering; **search remains global-read behind `search:query`**. This is a deliberate, time-boxed compromise, not an oversight. Note also that the runs index has no project field at all, so run search would remain global even after an ACL index lands.

### Query cost

- **One global-permission query per request.** FastAPI caches sub-dependency results per request keyed on the callable, and every `require_permission(...)` closure depends on the same `load_authz` function object, so it executes once even when a route stacks several permission checks. `request.state.authz` provides a second layer for code reaching the resolver outside the dependency graph.
- **At most one project-permission query per distinct project per request**, memoized in `_project_cache`.
- **Worst case is two additional indexed SELECTs per request.** For comparison, `authenticate_api_key` already performs a write and a `COMMIT` on every API-key request.
- **No cross-request caching in v1.** A process-level TTL cache makes revocation lag by the TTL, and across multiple Elastic Beanstalk instances that lag is nondeterministic. Deferred.

## Bootstrap and Administration

### Replacing "first user registered wins"

The current bootstrap grants `is_superuser` to whoever registers first, and is duplicated at `api/auth/services.py:132-137` and `api/auth/oauth2_service.py:463-468`. It has three defects:

1. **It is a race.** Two concurrent registrations against a multi-instance deployment both observe an empty `users` table and both become superusers; `SELECT ... LIMIT 1` under `READ COMMITTED` offers no protection.
2. **It is a privilege-escalation path on any empty database** — a restored-but-unseeded environment hands admin to whoever registers first.
3. **It is duplicated**, so the two copies can drift.

Both blocks are deleted and replaced by `assign_default_roles(session, user)` in `api/rbac/services.py`, called from both creation sites. It grants `DEFAULT_USER_ROLE`, and additionally grants `admin` and sets `is_superuser` if the username appears in `BOOTSTRAP_ADMIN_USERNAMES` (`source='bootstrap'`). A `scripts/grant_role.py` CLI provides break-glass access, following the style of the existing `scripts/reindex.py`.

### Configuration

New computed fields in `core/config.py`, following the established `_get_config_value` pattern (environment variable → AWS Secrets Manager → default):

| Setting | Default | Purpose |
|---------|---------|---------|
| `ENVIRONMENT` | `dev` | `dev`, `staging`, or `prod`. **Does not exist today** — tiers are currently distinguished only by which Elastic Beanstalk environment is deployed to. Nothing else here can be tier-gated until it exists. |
| `RBAC_MODE` | `dry_run`, then `enforce` | `off`, `dry_run`, or `enforce`. See below. |
| `DEFAULT_USER_ROLE` | `member` | Role auto-granted at user creation; empty disables |
| `BOOTSTRAP_ADMIN_USERNAMES` | *(empty)* | Comma-separated usernames granted `admin` + `is_superuser` at creation |
| `ORPHAN_PROJECT_OWNER` | *(empty)* | Optional username to adopt projects whose owner cannot be resolved during backfill |

### Admin API

New router `api/rbac/routes.py` at `/api/v1/rbac`:

| Method | Path | Permission |
|--------|------|------------|
| GET | `/rbac/permissions` | `role:read` — returns the catalog with resource, description, risk, and scopability |
| GET | `/rbac/roles` | `role:read` |
| POST | `/rbac/roles` | `role:manage` |
| GET | `/rbac/roles/{name}` | `role:read` |
| PATCH | `/rbac/roles/{name}` | `role:manage` — permission set only; builtin roles reject rename and scope change |
| DELETE | `/rbac/roles/{name}` | `role:manage` — `409` if builtin or if assignments exist |
| GET | `/rbac/users/{username}/roles` | `role:read` |
| POST | `/rbac/users/{username}/roles` | `role:manage` |
| DELETE | `/rbac/users/{username}/roles/{role_name}` | `role:manage` |

Project membership lives on the project router so that owners can self-serve:

| Method | Path | Permission |
|--------|------|------------|
| GET | `/projects/{project_id}/members` | `project:read` (project-scoped) |
| POST | `/projects/{project_id}/members` | `project:manage_members` |
| PATCH | `/projects/{project_id}/members/{username}` | `project:manage_members` |
| DELETE | `/projects/{project_id}/members/{username}` | `project:manage_members` |

And, required by the SPA so it can decide which controls to render rather than rendering everything and absorbing 403s:

| Method | Path | Auth |
|--------|------|------|
| GET | `/auth/me/permissions` | Authenticated |

```json
{
  "is_superuser": false,
  "global_roles": ["member", "lab_manager"],
  "global_permissions": ["project:read", "run:create", "run:demux", "..."],
  "projects": [
    { "project_id": "P-20260731-0001", "role": "project_owner",
      "permissions": ["project:read", "project:update", "project:manage_members"] }
  ]
}
```

### Guardrails

- The last `project_owner` cannot be removed from a project (`409`).
- A `scope=project` role cannot be assigned through the global endpoint, or vice versa (`400`).
- A user cannot revoke their own `role:manage` if they are the last non-superuser holder (`409`).
- Toggling `is_superuser` requires `user:manage` **and** superuser — never `role:manage` alone.
- Both `/rbac/*` reads and writes are themselves audited; enumerating who has access is worth recording.

## Rollout

Phase 1 — closing the 74 open routes — is the highest-value security work, but it is **not one pull request**. It spans five consumer systems, two of which currently send no credential at all. Shipping it as a single change is the most likely way this project gets rolled back.

| Phase | Content | Breaking | Done when |
|-------|---------|----------|-----------|
| **0** | Commit `.ebextensions/db-migrate.config`; add `ENVIRONMENT`; JSON logging + request-ID middleware; attach `OptionalUser` to all 74 open routes for identity logging only | No | 7 days of production logs exist and can answer "which open routes received anonymous traffic, from which user agents and IPs" |
| **1a** | Create service-account users and API keys; land and deploy consumer changes **while the endpoints are still open** | No | Logs show zero anonymous traffic from known consumers in all three tiers |
| **1b** | Close destructive and configuration writes: `PUT /settings/{key}` and every `DELETE` | **Yes** | Deployed to prod; no 401 spike from unknown callers |
| **1c** | Close remaining writes; stop honouring client-supplied `created_by` | **Yes** | As above |
| **1d** | Close reads | **Yes** | CI asserts every route not in `PUBLIC_ROUTES` returns 401 unauthenticated; 7 days with no anonymous non-public requests |
| **2** | RBAC schema, catalog seeding, resolver, `/auth/me` permission fields. **No route behaviour change** | No | Catalog present in all three tiers; resolution-matrix test passes; the diff touches no route's authorization |
| **3** | Membership backfill; admin API guarded by the existing `CurrentSuperuser` (no chicken-and-egg) | No | Admins can grant and revoke; the "projects with no member" report is empty or explicitly signed off |
| **4** | `require_permission` wired onto routes with `RBAC_MODE=dry_run` | No | 14 days in production dry-run, with every distinct `(principal, permission, route)` denial either resolved by a grant or explicitly accepted |
| **5** | `RBAC_MODE=enforce`, dev → staging → prod | **Yes** | 30 days in production enforce with no rollback |
| **6** | Row-level read filtering and pagination | **Yes** | Pagination tests pass; list totals reflect membership |
| **7** | Frontend permission gating, MCP hardening, access reporting | No | — |

**Phase 0 is not optional.** There is no request-logging middleware today, and therefore no inventory of who calls the 74 open routes. Skipping it means discovering consumers from a production outage. It uses `optional_current_user` (already present at `api/auth/deps.py:163`), which returns `None` rather than raising — zero behaviour change, but the caller's identity becomes available for logging.

Each breaking wave deploys dev → soak → staging → soak → prod.

### Verified Phase 1 blockers

Two consumers call the API with no credential whatsoever. Both are confirmed in source and both must be fixed in Phase 1a:

- **`GA4GH-WES-API-Service/src/wes_service/services/workflow_submission_service.py:174`** — `await client.get(f"{api_url}/api/v1/workflows/{workflow_id}")` with no headers. Recommended fix: forward the caller's bearer token, which WES has already validated, rather than a service key. This preserves per-user authorization for free.
- **`NGS360-ETL/load_json_to_db.py:989-992`** — four bare `requests.post()` calls to `/projects/search`, `/runs/search`, `/samples/search`, and `/qcmetrics/search`.

The same WES service validates every bearer token against `GET /api/v1/auth/me` and caches the token-to-username mapping (`src/wes_service/core/security.py`). Two consequences: `/auth/me`'s `username` field is a load-bearing contract, and role revocation is **not** immediate for WES. Bound that cache to five minutes or less and document the delay.

### Enforcement mode

`RBAC_MODE` gates *authorization* only:

```python
@computed_field
@property
def RBAC_MODE(self) -> str:
    """off | dry_run | enforce. Invalid values fail CLOSED."""
    default = "enforce" if self.ENVIRONMENT == "dev" else "dry_run"
    value = self._get_config_value("RBAC_MODE", default=default).strip().lower()
    if value not in ("off", "dry_run", "enforce"):
        return "enforce"          # a typo must never mean "off"
    if value == "off" and self.ENVIRONMENT == "prod":
        return "dry_run"          # "off" is unreachable in prod
    return value
```

Four properties matter:

- **Invalid values fail closed.** `RBAC_MODE=enforced` must not silently disable authorization.
- **The default tightens in code, not in configuration.** The literal moves from `dry_run` to `enforce` in the Phase 5 release, so an environment that never sets the variable ends up enforcing. This is the actual antidote to a kill switch left on — the switch decays toward safe.
- **`off` is unreachable in production**, clamped to `dry_run`.
- **`RBAC_MODE` must not move into the database `Setting` table**, even though `plans/db-backed-settings-migration.md` proposes migrating configuration there. A `PUT /settings/RBAC_MODE` that disables authorization is self-defeating. Add it to that plan's bootstrap-only list.

**There is deliberately no runtime kill switch for authentication.** Such a switch would mean shipping code capable of serving `PUT /settings/{key}` unauthenticated in production on a single `eb setenv` typo. Phase 0's logging already provides everything a dry-run authentication mode would, without the hazard. Authentication closure is code-gated and deployed per tier. The one escape hatch is an `AUTH_OPEN_ROUTES` allowlist of route *names*, empty by default, with a startup error if it is non-empty in production.

**Dry-run behaviour.** Resolve the decision, stash it on `request.state`, and emit exactly one `event=rbac.decision` log line per request — not one per dependency — carrying `decision`, `mode`, `permission`, `scope`, `principal`, `auth_method`, `route_name`, `method`, `path`, `request_id`, and `client_app`. In non-production tiers, also return an `X-RBAC-Decision` header so developers see denials without opening CloudWatch.

Dry-run necessarily lets a should-be-denied write succeed. That is acceptable for reads and ordinary writes, but a small `ALWAYS_ENFORCE` set hard-denies even in dry-run: `PUT /settings/{key}`, every `DELETE`, and all role-grant routes. These have near-zero legitimate traffic, so there is no discovery value in dry-running them and real damage potential in doing so.

**Operational hygiene.** Log a startup banner at ERROR when `RBAC_MODE=dry_run` and `ENVIRONMENT=prod`. Alarm in CloudWatch if production still reports `dry_run` past the cutover date. Expose `GET /api/v1/rbac/status` (authenticated) returning `{environment, rbac_mode, permission_count, seeded_at}` so "is it actually on?" is a two-second question — and keep mode off the public `/api/health`.

**Rollback is `eb setenv RBAC_MODE=dry_run`** — roughly one to three minutes, no deploy, no migration. Note that `get_settings()` is `lru_cache`d, so this takes effect via the worker restart that an Elastic Beanstalk environment-property change triggers; it is not a hot toggle. This, not `alembic downgrade`, is the rollback path.

## Migration

### Prerequisite: the untracked migration hook

`.ebextensions/db-migrate.config` runs `alembic upgrade head` on deploy — `leader_only`, from `/var/app/staging`, before the application is promoted to `/var/app/current`. **It is currently untracked in git.** Migrations have therefore been applied by hand, and the three databases (`ngs360_dev`, `ngs360_staging`, `ngs360`, all on one RDS instance) are likely at different revisions; the untracked `scripts/compare_schemas.py` suggests this drift is already suspected.

Committing the file makes the *next* deploy silently apply whatever backlog exists to production, inside `container_commands`, before promotion, with no snapshot. Required sequence:

1. Query `alembic_version` in all three databases.
2. Reconcile any drift manually.
3. Open a pull request committing the file **plus one no-op revision**.
4. Deploy to dev; confirm via `eb logs` that `01_db_migrate` ran and `alembic current` matches head.
5. Deploy to staging.
6. **Take an RDS snapshot**, then deploy to production.

### Revision ordering

Four revisions, not one. MySQL DDL is not transactional, so a revision that fails halfway leaves partial state with no rollback.

| # | Revision | Contents | Downgrade |
|---|----------|----------|-----------|
| 1 | `rbac_0001_tables` | `role`, `role_permission`, `user_role`, `project_member`. Additive only. | Drop tables — safe |
| 2 | `rbac_0002_user_shells` | Ensure a `users` row exists for every username the backfill references | Delete only rows tagged `source='migration'` |
| 3 | `rbac_0003_backfill_members` | `INSERT ... SELECT` guarded by `NOT EXISTS`; idempotent; every row tagged `source='migration'` | Delete only `source='migration'` rows |
| 4 | `rbac_0004_constraints` | Unique constraints and indexes. **Ship in a later release than 1–3.** | Drop them |

Because migrations run before promotion, `leader_only`, with no blue/green deployment, there is always a window in which **old code runs against the new schema on every instance**. Every revision must therefore be backward-compatible with the previous application version: additive only, no `NOT NULL` on existing tables, constraints deferred a release.

### Catalog seeding: at startup, not in a migration

The permission catalog is code derived from the route table, and it will change on most feature pull requests. Putting it in migrations means a new Alembic revision per new permission, which guarantees drift within two sprints. Instead, `sync_rbac_catalog()` runs in `core/lifespan.py` alongside the existing `sync_env_to_settings()`. Rollback is automatic: deploying old code restores the old catalog.

Three implementation requirements:

- **All four Gunicorn workers run lifespan.** `sync_env_to_settings()` is already racy but benign; catalog seeding is not. Take a MySQL advisory lock — `SELECT GET_LOCK('ngs360_rbac_seed', 10)` — around the seed.
- **Never `DELETE`.** Seeding upserts `role` and `role_permission` rows for `is_builtin` roles only. Admin-created roles and *all* grants are never touched. Removing a permission from the catalog in code marks it inactive; a delete would cascade grants away.
- **Fail startup on seed failure when enforcing.** `sync_env_to_settings()` currently swallows exceptions with a warning; for RBAC that is wrong, because an empty catalog plus `enforce` is a site-wide 403. If `RBAC_MODE=enforce` and the catalog is empty, refuse to start — failing `/api/health` and letting the load balancer pull the instance is far better than serving an outage as 403s.

### Membership backfill

`Project.created_by` is the obvious ownership source and the wrong one. It is a free-text username with no foreign key, and revision `49e7d06e7eb4` populated it from `projectattribute` keys `('createby','createdby','businessowner','Business Owner')` — where the `'Business Owner'` arm compares a literal containing a space and a capital against `LOWER(key)` and therefore **never matches** — falling back to the literal `'unknown'`.

A sample of production data indicates the historical population is dominated by a handful of bulk loaders appearing as `created_by` on large numbers of projects they did not own, with the real owner recorded in a `businessowner` or `dataowner` attribute. Newer UI-created projects have the inverse problem: `created_by` is a good username, but the `Business Owner` attribute holds a display name rather than a username.

> **Confirm before implementing.** Re-run the orphan and attribute-coverage queries against production and record the actual figures here. The backfill strategy depends on them, and the sample above was not independently verified.

Recommended precedence, applied per project:

1. `projectattribute` where `LOWER(key)` ∈ {`businessowner`, `business owner`, `dataowner`, `data owner`} → `project_owner`
2. `LOWER(key)` ∈ {`ngsanalyst`, `ngs analyst`, `tbioanalyst`, `tbio analyst`} → `project_contributor`
3. `LOWER(key)` ∈ {`createby`, `createdby`} → `project_contributor`
4. `project.created_by`, if it is not `'unknown'` and steps 1–3 produced nothing → `project_owner`
5. Otherwise → **unresolved report**

Matching is `LOWER(TRIM(value))` against `LOWER(users.username)`. Values that are not usernames (display names, `"Unknown"`) fall to step 5 rather than being silently dropped. **A project with no member is a project nobody can edit** — the single most likely source of support tickets after the enforce cutover. `admin` holds global `project:manage_members` so an administrator can adopt orphans, and `ORPHAN_PROJECT_OWNER` can assign them in bulk.

Also backfilled: every user with `is_superuser = 1` receives the global `admin` role; every other active user receives `DEFAULT_USER_ROLE`. `is_superuser` and `get_current_superuser` are retained for at least two releases as the break-glass path when RBAC data proves wrong.

### The duplicate-user hazard, which must be fixed before any backfill

`find_or_create_oauth_user` (`api/auth/oauth2_service.py:438-461`) matches existing users **by email only**, then resolves username collisions by appending a counter. If the backfill creates a shell `users` row for `jdoe` without that person's exact corporate email, then when they sign in via SSO the email lookup misses, a second row is created, and they become `jdoe1` — a distinct identity with zero grants, while every membership row stays attached to the orphan. This fails silently and will happen to **every** backfilled user.

Two changes, the first required:

- **Required:** after the email lookup misses, match case-insensitively on `username` and *claim* an unclaimed shell row (`hashed_password IS NULL` and no linked `OAuthProvider`) rather than creating a duplicate, backfilling the SSO email at claim time.
- **Best effort:** resolve username to corporate email through the already-configured LDAP path (`api/users/ldap_service.py`) when creating shells, so the email match succeeds directly.

The username-deduplication loop is a pre-existing bug — two identities for one person — that RBAC makes actively dangerous, because one of them holds the grants.

### Rollback

**`alembic downgrade` is not the rollback plan.** In-place deploys, no blue/green, and non-transactional MySQL DDL make downgrading a live production schema a data-loss risk. The rollback is `eb setenv RBAC_MODE=dry_run`, followed by a forward fix — granting the missing role — rather than a redeploy.

`downgrade()` must still be written and exercised in CI (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`) as a development convenience and as a correctness check on each revision.

## Consumer Requirements

| Consumer | Required change | Owner | Blocking |
|----------|-----------------|-------|----------|
| **MCP server** | Dedicated service account + least-privilege role; key-level scope narrowing; non-retryable structured 403 handling | `NGS360/mcp-server` | 1a, 5 |
| **Frontend SPA** | Route-loader error boundaries; permission-based gating; regenerate the API client | `NGS360/frontend-ui` | 5 (UX only) |
| **GA4GH WES** | Forward the caller's bearer token on `GET /workflows/{id}`; bound the `/auth/me` token cache to ≤5 min | `GA4GH-WES-API-Service` | **1c/1d** |
| **NGS360-ETL** | Service-account key on the four reindex posts | `NGS360-ETL` | **1c** |
| **NGS360-Agent** | Inherits the MCP decision | `NGS360-Agent` | 5 |
| **`APIServer/scripts/*`** | Admin-only; add an `--operator` argument writing one audit row per run | this repo | 3 |

### MCP server: one API key for all traffic

`ngs360_mcp_server/server.py` constructs a single `NGS360Client` at server start from `NGS360_API_TOKEN`, shared by all 82 tools, running `stateless_http`. One key means one user means one role for every agent request.

| Option | Effort | Attribution | Verdict |
|--------|--------|-------------|---------|
| Dedicated service account with an explicit least-privilege role | Low | None — all traffic is the service identity | **v1** |
| Key-level scope narrowing (`api_keys.scope_permissions`, intersection only) | Low | n/a | **v1** |
| Per-user token passthrough (MCP OAuth) | High — requires threading a per-request identity through 82 tools | Full | Deferred, not foreclosed |

v1 requires both of the first two. Create `svc-ngs360-mcp` holding exactly `service_account` — or `auditor`, if the deployment turns out to be read-only, which should be confirmed before granting write permissions — and add key scoping so a key can never exceed its owner's role even if that account is later mis-flagged. Scoped keys are the right primitive regardless of which identity model eventually wins, so building them now is not wasted work.

Two notes that will otherwise cost someone an afternoon:

- A service-account user must be created with **both** `is_active` and `is_verified` true, or its API key fails on every route using `get_current_active_user`.
- `authenticate_api_key` writes `last_used_at` and **commits on every request** (`api/auth/deps.py:57`). That is write amplification independent of RBAC and deserves its own ticket — throttle to once per N minutes.

On attribution: rather than an impersonation header, which widens access if mis-implemented, record the end-user identity as **audit context only** in an `on_behalf_of` field, with authorization still evaluated against the service account. State that trade-off plainly rather than implying the agent enforces per-user access, because it does not.

**Required regardless of identity model:** the MCP client calls `raise_for_status()` with no handling anywhere in the package. A 403 surfaces as an `httpx.HTTPStatusError` traceback inside a tool result, and a model will retry it. Map 401 and 403 to a structured, explicitly **non-retryable** tool error — *"Permission denied: {detail}. Not retryable — ask the user to request access to {scope}."* An agent looping on denied writes is a real and expensive failure mode.

### Frontend

`src/lib/error-utils.ts` already classifies 403 ("You don't have access to this"), and `fetchWithAuth` correctly does **not** retry it — only 401 triggers a refresh. The real gaps are elsewhere:

- Route **loaders** using `ensureQueryData` in `beforeLoad` throw into router error boundaries rather than the form-level `classifyError` paths. Each route's `errorComponent` needs auditing.
- UI gating is `is_superuser`-only (`src/routes/_auth.admin.route.tsx`). Replace with a permission check, keeping `is_superuser` as an implicit allow.
- Hide, rather than disable, actions the user lacks; add an inline access-denied state for read pages.
- `src/client/` is generated from `/openapi.json` via `@hey-api/openapi-ts`, whose config points at the docker-compose service, so regeneration requires the new API server running locally. The backend merges first.

Note the deployment coupling: `deploy.sh` builds the SPA into `APIServer/static/` and ships it in the same `eb deploy --staged` artifact. Frontend and backend are one deployment. That makes releases atomic, but it also means there is no frontend-only hotfix, and every UI fix pays the migration-running deploy path. Keep UI gating advisory so a stale UI is cosmetic, never a security hole — the server is the enforcement point.

### API contract

**Additive only.** `roles` and `permissions` on `GET /auth/me`; a new `GET /auth/me/permissions`; `my_permissions` on the project detail response; the `/rbac/*` router. `UserPublic.username` must be preserved — WES reads it on every authenticated request.

Project-scoped permissions are **not** inlined into `/auth/me`; with a five-figure project count the payload is unbounded. They belong on the project detail response.

**403 response body:** keep `detail` a plain string. The frontend's `extractDetail` accepts a string or an array of `{msg}` objects; a dict would silently fall through to generic copy. Structure goes in sibling keys:

```json
{
  "detail": "Missing permission: project:update on project P-20260731-0001",
  "required_permission": "project:update",
  "scope": "project:P-20260731-0001"
}
```

**403 versus 404:** return **404 for reads of resources the caller cannot see**, and **403 for writes or actions on resources they can see**. NGS360 project identifiers are semantically meaningful, so existence disclosure matters. This choice determines what every test asserts and what the UI renders, so it must be settled before Phase 4.

**`POST /files/upload` `created_by`:** accepted-and-ignored from Phase 1c with a deprecation header, so the generated client keeps compiling; removed in Phase 5.

## Testing

### Why the existing suite will fail

`tests/conftest.py` overrides `get_current_user` with a `User(...)` constructed **on every call** and never inserted into the test database. Each request therefore sees a different `uuid4` matching no row, so every database-backed role lookup returns nothing and every `require_permission` denies. Roughly 32 test modules under `tests/api/` are affected.

### Required changes, in order

1. **Refactor first.** `client_fixture`, `superuser_client_fixture`, and `unauthenticated_client_fixture` are near-identical 40-line blocks. Collapse them onto one `_make_client(session, user=None)` helper *before* adding RBAC, or the duplication becomes eightfold.
2. **Persist the fixture users.** Create real `User` rows in the `session` fixture and have the override close over the persisted instance, built once rather than per call. This is fixture-internal and requires no test-module edits.
3. **Give the default `client` a legacy-equivalent role** whose permission set is exactly what the pre-RBAC API allowed an authenticated user to do. Existing tests then pass unchanged. This is both how the rewrite of 32 modules is avoided *and* a precise executable specification of the old behaviour.
4. **Pin the mode.** Set `RBAC_MODE=enforce` in `isolate_test_environment` so tests always exercise the strict path. The existing `reset_settings_cache` fixture clears the `lru_cache` per test, so per-test `monkeypatch.setenv` still works for dry-run cases.
5. Add a parametrizable `client_as(global_roles=..., project_roles=...)` factory rather than more fixture copies.

Budget for genuinely touching five to ten modules where tests relied on unauthenticated access — `tests/api/test_settings.py` calling `PUT /settings/{key}` is the obvious one — not all 32.

### Required new coverage

| Test | What it protects |
|------|------------------|
| **Permission-resolution matrix** | Table-driven over `(global_roles, project_roles, is_superuser, key_scope, permission, scope)`. Pure function, no HTTP. Highest value per line. |
| **Route-coverage guard** | Walk `app.routes`, inspect `route.dependant.dependencies`, and assert every route is either in a hardcoded `PUBLIC_ROUTES` list or carries an authentication dependency. Fails CI the moment someone adds a route without deciding — this is what prevents drift back to 74 open routes. |
| **Unauthenticated-closure regression** | Parametrized over every non-public route: `unauthenticated_client` must get **401**, not 200 and not 500. |
| **Negative 403 tests** | Per permission family; assert status, that `detail` is a string, and that `required_permission` is present. |
| **Cross-project isolation** | A member of P1 gets 403 or 404 on every project-scoped route for P2. |
| **Pagination under filtering** | Create 25 projects, make the user a member of 7, assert `total_items == 7`, page 1 returns 7 rows, `has_next is False`. Catches post-filtering directly. |
| **Dry-run semantics** | A would-be-denied request returns 2xx and emits exactly one denial log line; an `ALWAYS_ENFORCE` route returns 403 even in dry-run. |
| **Seeding idempotence** | Run `sync_rbac_catalog()` twice; row counts stable; a manually created role and a manual grant both survive. |
| **Migration round-trip** | Upgrade, backfill, assert every project has a member or appears in the unresolved report, downgrade, upgrade. |
| **Superuser break-glass** | Still bypasses every check. |
| **`/auth/me` contract** | `username` present and a string — WES depends on it. |

## Audit Logging

### Tier A — structured logs (Phase 0, mandatory, no schema)

Replace the 12-line `basicConfig` in `core/logger.py` with a JSON formatter and add request-ID middleware to `main.py`, which currently registers only `CORSMiddleware`. Elastic Beanstalk already ships stdout to CloudWatch.

Fields: `timestamp`, `request_id`, `principal`, `principal_id`, `auth_method`, `api_key_prefix`, `client_app`, `source_ip`, `method`, `path`, `route_name`, `status`, `duration_ms`, `rbac_mode`, `rbac_decision`, `required_permission`, `scope`.

This is not only audit — it is the instrument that makes the rollout safe. Without it, Phase 0's blast-radius measurement and Phase 4's denial punch-list are both impossible.

### Tier B — durable `audit_log` table (Phase 3/4)

Mutations and grants only, never every request. Columns: `id`, `occurred_at`, `request_id`, `actor_user_id`, `actor_username`, `on_behalf_of`, `auth_method`, `api_key_id`, `action`, `object_type`, `object_id`, `project_id`, `outcome`, `reason`, `source_ip`, `client_app`, `changes` (JSON, changed fields only).

Minimum event set:

- Every role and membership grant or revoke
- Authentication events: login success and failure, API key created, revoked, and first used, password change
- `PUT /settings/{key}` — every write, with before and after values
- Every `DELETE` across the API
- Project create, update, and patch; vendor create, update, and delete; job submit
- Every **denied** authorization decision — Tier A covers allows; denials go to the table so administrators can answer "why did this fail" without CloudWatch access

**Transaction policy:** grants and settings writes are audited in the **same transaction** as the mutation, so an audit failure aborts the grant. Bulk data writes are best-effort after commit, so an audit failure does not break a 200-file upload.

**Retention:** `audit_log` grows without bound on MySQL. A partitioning or archival plan — or at minimum a row-count alarm — is required before enabling the write-heavy events.

Deferred: read auditing, an audit UI, tamper-evidence, and S3 archival.

## Operations

### Answering the two questions that matter

Both as first-class endpoints rather than ad-hoc SQL, so they stay correct as the model evolves:

- `GET /api/v1/rbac/projects/{project_id}/access` → for each principal: user, role, `source` (`direct`, `global`, or `superuser`), `granted_by`, `granted_at`, effective permissions. **This must include the implicit paths** — global roles, superusers, service accounts — or the answer is wrong in the dangerous direction.
- `GET /api/v1/rbac/users/{username}/access` → global roles, project memberships, effective permission set, active API keys and their scopes, last activity.

Both are audited. A read-only script wrapper provides break-glass when the API is itself the broken thing.

**There must be exactly one resolver function.** Effective permissions are a union of four inputs (superuser, global roles, project role, intersected with any API-key scope). That union is computed in one place and called by `require_permission`, by `/auth/me`, and by both reporting endpoints. Reimplementing it in the reporting path is how "who can access project X" starts lying — and it will lie during an incident, which is the only time anyone asks.

### Detecting over-tight permissions

- CloudWatch metric filter on `event=rbac.decision decision=deny`, dimensioned by `route_name` and `principal`; alarm on rate spikes after each cutover.
- A dashboard of the top 20 `(principal, permission, route)` denial tuples over 24 hours. During Phase 4 this *is* the punch list.
- **Any denial for `svc-ngs360-mcp`, `svc-wes`, or `svc-etl` should be zero.** Alarm on the first one — it is a misconfiguration, not user error.
- 401 rate on newly closed routes after each Phase 1 wave: the "consumer we forgot" signal.
- A gauge of users holding zero roles. It should trend to zero; anything else means new users are landing without access.

### Detecting over-broad permissions

- Count of `admin` role holders and `is_superuser = 1` rows; alarm on any increase.
- Active API keys; keys with no expiry; keys unused for more than 90 days.
- Grants made by non-administrators or outside business hours.
- A weekly report of any permission held by more than a threshold share of users — such a permission is either doing nothing and should be folded into the base role, or is a mistake.
- Projects with an unusually large membership, and projects whose only member came from the backfill fallback.
- A gauge of `rbac_mode` per tier, alarming if production is not `enforce` past the cutover date.

## Known Gaps and Open Issues

These are limitations of the design or pre-existing problems that RBAC interacts with. They are recorded here rather than left implicit.

1. **`PUT /api/v1/settings/{key}` is unauthenticated in production today.** Close it as a standalone hotfix if Phase 1b is not imminent.
2. **Actor-field spoofing must be fixed alongside Phase 1c, or RBAC is theatre.** `POST /files/upload` accepts `created_by` as a client-supplied form field (`api/files/routes.py:89`), and `FileCreate` / `FileUpdate` accept it on the JSON paths. Once authenticated, these must be overwritten from the principal server-side. The ownership backfill depends on provenance that is currently caller-asserted.
3. **No offboarding path.** With local database assignment and no directory sync, grants only accumulate: a departed employee retains roles, memberships, and API keys indefinitely. An access-control system with no revocation path is weaker than the honest absence of one. v1 requires at minimum a periodic job reporting users no longer resolvable in LDAP — the plumbing already exists (`LDAP_ENABLED=true` in staging and prod, `api/users/ldap_service.py`) — even if it only produces a report.
4. **Direct-database bypass channels.** `ngs360-sql-langgraph-agent` runs natural-language SQL across the whole schema; `APIServer/scripts/*` and the ETL write directly to the database and S3. API-level RBAC is a partial control while these exist, and they also bypass the audit trail. Named owners and a follow-up are required; least-privilege database users are the mechanism.
5. **OpenSearch is not ACL-aware**, so the five `*/search` endpoints remain global-read behind `search:query` in v1. The runs index has no project field at all, so run search stays global even after an ACL index lands.
6. **`manifest:*` and `file:browse` cannot be project-scoped** without an S3-URI-to-project resolver.
7. **`is_superuser` and the `admin` role are two sources of truth.** This is unavoidable if break-glass is retained, and it should be. Mitigated by policy — `is_superuser` is set only via `BOOTSTRAP_ADMIN_USERNAMES` or `user:manage`, never used for routine access — and by surfacing both on `GET /auth/me`.
8. **Settings must never hold secrets.** `Setting.value` is a plaintext column, and `setting:read` is in `member`. Either remove `setting:read` from `member` (check the UI's need for bucket URIs first) or treat "no secrets in settings" as a standing constraint.
9. **Environment credential hygiene.** `staging.env` and `prod.env` are present in the working tree containing live RDS and OpenSearch passwords. Not caused by RBAC, but an access-control design that ignores credential handling is incomplete; these belong in Secrets Manager, which the configuration layer already supports.

## Non-Goals

Deliberately out of scope for v1:

| Item | Rationale / future shape |
|------|--------------------------|
| Deny or negative permissions | Grant-only by design; precedence lattices are unauditable |
| ABAC, time-bounded grants, approval workflows | No requirement; `granted_at` is present if expiry is added later |
| Sub-project ACLs (per-sample, per-file) | The project is the finest authorization grain; `File.is_public` is unchanged |
| AD / LDAP group-to-role sync | **Not precluded** — add `role_group_mapping` plus a sync job touching only `source='directory'` rows. The `source` column and the existing `LDAP_*` configuration are the hooks. |
| SSO-claim-driven roles, JWT scope claims | The token stays `{sub, exp, iat, type}`. `get_current_user` reloads the user per request, so database roles need no token change and revocation is immediate. |
| Full RBAC change history | v1 records current state (`granted_by`, `granted_at`) only. **Known gap: revocations leave no trace** until the Tier B audit table lands. |
| Cross-request permission caching | Needs explicit invalidation across Elastic Beanstalk instances |
| API-key permission scopes beyond the MCP case | Intersection-only narrowing ships for service accounts; general key scoping is v2 |
| Project-scoping the S3 passthrough endpoints | Requires a URI-to-project resolver |
| Run-scoped or vendor-scoped roles | The two-table schema is deliberately not polymorphic; a third scope means a third table |
| Admin UI for role management | API only in v1 |
| Rate limiting, per-role quotas | Unrelated concern |

## Source Files

| File | Description |
|------|-------------|
| `api/rbac/permissions.py` | `Permission` enum, `PermissionSpec`, `CATALOG`, `PROJECT_SCOPABLE`, `ALL_PERMISSIONS` |
| `api/rbac/roles.py` | `ROLE_DEFINITIONS` — builtin global and project roles with their permission sets |
| `api/rbac/models.py` | `Role`, `RolePermission`, `UserRole`, `ProjectMember`, `RoleScope`, `GrantSource` |
| `api/rbac/deps.py` | `AuthzContext`, `load_authz`, `require_permission()`, `require_project_permission()`, `project_scope()` |
| `api/rbac/services.py` | The single resolver, `assign_default_roles()`, `sync_rbac_catalog()`, role and membership CRUD |
| `api/rbac/routes.py` | `/rbac/permissions`, `/rbac/roles`, `/rbac/users/{u}/roles`, `/rbac/status`, access reporting |
| `api/auth/deps.py` | Unchanged; `load_authz` layers onto `get_current_active_user` |
| `api/auth/services.py` | Remove the "first user wins" block; call `assign_default_roles()` |
| `api/auth/oauth2_service.py` | Remove the duplicate bootstrap; claim unclaimed shell users by username |
| `api/auth/routes.py` | `GET /auth/me` gains `roles` and `permissions`; new `GET /auth/me/permissions` |
| `api/project/deps.py` | `ProjectDep` becomes a sub-dependency of `require_project_permission` |
| `api/project/routes.py` | Membership endpoints; `ProjectDep` replaced by permission-carrying aliases |
| `main.py` | Router registration with default authentication; `rbac_router` |
| `core/config.py` | `ENVIRONMENT`, `RBAC_MODE`, `DEFAULT_USER_ROLE`, `BOOTSTRAP_ADMIN_USERNAMES`, `ORPHAN_PROJECT_OWNER` |
| `core/lifespan.py` | `sync_rbac_catalog()` with an advisory lock and a fail-closed startup assertion |
| `core/logger.py` | JSON formatter for structured audit logging |
| `alembic/env.py` | Import the new RBAC models |
| `alembic/versions/rbac_0001_tables.py` | The four tables |
| `alembic/versions/rbac_0002_user_shells.py` | Shell users for backfill targets |
| `alembic/versions/rbac_0003_backfill_members.py` | Membership backfill and the unresolved report |
| `alembic/versions/rbac_0004_constraints.py` | Constraints and indexes, one release later |
| `.ebextensions/db-migrate.config` | Must be committed before any migration phase |
| `scripts/grant_role.py` | Break-glass role assignment CLI |
| `tests/conftest.py` | Consolidated client fixtures, persisted users, `client_as()` factory |
| `tests/api/test_rbac_resolution.py` | Permission-resolution matrix |
| `tests/api/test_rbac_enforcement.py` | Negative 403 tests, cross-project isolation, dry-run semantics |
| `tests/test_route_coverage.py` | Route-coverage guard and unauthenticated-closure regression |
