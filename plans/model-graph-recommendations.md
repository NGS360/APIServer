# Model Graph — Improvement Recommendations

**Date**: 2026-04-24  
**Status**: Recommendations for review — no circular dependencies found, but several structural improvements would reduce confusion and bugs.

## 1. 🐛 ProjectAttribute Naming Mismatch

**File**: `api/project/models.py`  
**Severity**: Confusing (not a bug, but misleading)

The back_populates names suggest a many-to-many relationship, but this is a one-to-many:

```python
# ProjectAttribute side
projects: List["Project"] = Relationship(back_populates="attributes")  # ← plural "projects"

# Project side
attributes: List[ProjectAttribute] | None = Relationship(back_populates="projects")
```

`ProjectAttribute.projects` is a `List["Project"]` but each attribute belongs to **one** project (via `project_id` FK). This should be singular:

```python
# ProjectAttribute side — RECOMMENDED
project: "Project" = Relationship(back_populates="attributes")  # singular

# Project side — no change needed
attributes: List[ProjectAttribute] | None = Relationship(back_populates="project")
```

Compare with `SampleAttribute` which does this correctly:
```python
sample: "Sample" = Relationship(back_populates="attributes")  # ✅ singular
```

## 2. 🐛 ProjectAttribute Has Double Primary Key

**File**: `api/project/models.py:23-24`  
**Severity**: Bug (potential)

```python
class ProjectAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    project_id: uuid.UUID = Field(foreign_key="project.id", primary_key=True)  # ← also PK!
```

`project_id` is marked as `primary_key=True` alongside `id`. This creates a composite primary key `(id, project_id)` instead of the intended simple PK on `id` with a FK on `project_id`. Compare with `SampleAttribute` which does it correctly:

```python
class SampleAttribute(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sample_id: uuid.UUID = Field(foreign_key="sample.id")  # ✅ FK only, not PK
```

**Fix**: Remove `primary_key=True` from `project_id`.

## 3. ⚠️ Missing Cascade Definitions on Parent → Child Relationships

**Severity**: Risk of orphaned rows on deletion

Entities with `cascade: "all, delete-orphan"`:
- ✅ `File` → hashes, tags, samples, all junction tables
- ✅ `QCRecord` → pipeline_metadata, metrics
- ✅ `QCMetric` → values, samples

Entities **missing** cascade:
- ❌ `Project` → `ProjectAttribute` — deleting a project leaves orphaned attributes
- ❌ `Project` → `Sample` — deleting a project leaves orphaned samples
- ❌ `Project` → `QCRecord` — deleting a project leaves orphaned QC records
- ❌ `Sample` → `SampleAttribute` — deleting a sample leaves orphaned attributes  
- ❌ `Workflow` → `WorkflowAttribute`, `WorkflowRegistration`, `WorkflowRun`
- ❌ `WorkflowRun` → `WorkflowRunAttribute`
- ❌ `Pipeline` → `PipelineAttribute`, `PipelineWorkflow`
- ❌ `SequencingRun` → `QCRecord` (intentional? re-demux does manual cleanup)

**Recommendation**: Add `sa_relationship_kwargs={"cascade": "all, delete-orphan"}` to parent-side relationships where the child cannot exist without the parent. Be cautious with `Project → Sample` and `Project → QCRecord` — these may be intentionally non-cascading if you want to prevent accidental mass deletion.

## 4. ⚠️ Auth Models Have FKs but No ORM Relationships

**File**: `api/auth/models.py`  
**Severity**: Minor (works via manual queries, but inconsistent with rest of codebase)

`RefreshToken`, `PasswordResetToken`, `EmailVerificationToken` all have `username FK → users.username`, and `OAuthProvider`, `APIKey` have `user_id FK → users.id`, but none declare `Relationship()` back to `User`, and `User` has no relationship lists.

This means you can't do `user.refresh_tokens` or `token.user` — you always have to write manual `select()` queries. If these are intentionally simple/flat, that's fine. But if you ever want cascade deletes (e.g., deleting a user deletes their tokens), you'll need ORM relationships.

## 5. ⚠️ Duplicate `Attribute` Schema Classes

Three modules define their own `Attribute(SQLModel)` class with identical fields:

| Module | Location |
|--------|----------|
| `api/project/models.py:17` | `Attribute(key, value)` |
| `api/samples/models.py:15` | `Attribute(key, value)` |
| `api/workflow/models.py:20` | `Attribute(key, value)` |

`api/pipeline/models.py` already imports it from `api.workflow.models` rather than duplicating.

**Recommendation**: Extract to a shared location:

```python
# core/models.py (or core/schemas.py)
class Attribute(SQLModel):
    key: str | None
    value: str | None
```

Then import from there in all three modules. This reduces duplication and ensures consistency.

## 6. 💡 SampleSequencingRun Has No ORM Relationships

**File**: `api/runs/models.py:270`  
**Severity**: Design choice, but inconsistent

`SampleSequencingRun` is a junction table with FKs to `sample.id` and `sequencingrun.id`, but declares no `Relationship()` back to either `Sample` or `SequencingRun`. Compare with:

- `FileSample` — has `Relationship()` to both `File` and `Sample` ✅
- `QCMetricSample` — has `Relationship()` to `QCMetric` ✅
- `SampleSequencingRun` — has **no** relationships ❌

This means you can't navigate from `SequencingRun` to its `Sample` objects via ORM (e.g., `run.samples`). The code always does manual `select(SampleSequencingRun).where(...)` queries.

**Recommendation**: Add relationships to enable ORM navigation:

```python
class SampleSequencingRun(SQLModel, table=True):
    # ... existing fields ...
    sample: "Sample" = Relationship()
    sequencing_run: "SequencingRun" = Relationship()
```

And on the parent sides:
```python
# In SequencingRun
sample_associations: List["SampleSequencingRun"] = Relationship(back_populates="sequencing_run")

# In Sample
run_associations: List["SampleSequencingRun"] = Relationship(back_populates="sample")
```

## 7. 💡 File Junction Tables Missing Reverse Relationships to Entities

**File**: `api/files/models.py`  
**Severity**: Inconsistent, limits navigation

`FileProject`, `FileSequencingRun`, `FileQCRecord`, `FileWorkflowRun`, `FilePipeline` all have `Relationship(back_populates="...")` to `File`, but **none** have a relationship back to their entity. For example:

```python
class FileSequencingRun(SQLModel, table=True):
    file: "File" = Relationship(back_populates="sequencing_runs")  # ✅ to File
    # Missing: sequencing_run: "SequencingRun" = Relationship(...)  # ❌
```

This means you can navigate `File → FileSequencingRun → .sequencing_run_id` (UUID only), but not `File → FileSequencingRun → .sequencing_run` (full object). Compare with `FileSample` which **does** have both directions.

**Recommendation**: Add entity-side relationships if you need ORM-level navigation from files to their parent entities. If you only ever resolve via explicit queries, this is acceptable but inconsistent.

## 8. 💡 Decouple `search/models.py` from Domain Response Models

**File**: `api/search/models.py`  
**Severity**: Coupling (not circular, but tight)

`search/models.py` imports `ProjectPublic`, `ProjectsPublic`, `SequencingRunPublic`, `SequencingRunsPublic` at runtime. This creates the dependency: `search → project → runs → jobs`.

If search response shapes ever diverge from the domain responses (e.g., search returns a subset of fields, or includes a relevance score), this coupling becomes painful.

**Recommendation**: Consider defining search-specific response models that are structurally similar but independently defined, or use `TypeAlias` references.

## Summary — Priority Order

| # | Issue | Type | Impact |
|---|-------|------|--------|
| 1 | ProjectAttribute naming mismatch | 🐛 Bug-adjacent | Confusing for developers |
| 2 | ProjectAttribute double PK | 🐛 Bug | Unintended composite PK |
| 3 | Missing cascades on parent→child | ⚠️ Risk | Orphaned rows on deletion |
| 4 | Auth models missing relationships | ⚠️ Inconsistent | Manual queries required |
| 5 | Duplicate `Attribute` classes | ⚠️ Duplication | Drift risk |
| 6 | SampleSequencingRun missing relationships | 💡 Enhancement | Can't ORM-navigate run↔sample |
| 7 | File junction tables missing entity-side relationships | 💡 Enhancement | Inconsistent with FileSample |
| 8 | search/models.py coupling | 💡 Enhancement | Tight coupling across domains |
