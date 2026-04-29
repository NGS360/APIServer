# Q3: Sample.project_id — String FK vs UUID FK

## The Situation Today

Your [`Project`](api/project/models.py:29) table has **two identifiers**:

| Column | Type | Role |
|--------|------|------|
| `id` | UUID | Internal primary key (auto-generated, e.g. `a3f8c1d2-...`) |
| `project_id` | String (unique) | Human-readable business identifier (e.g. `P-20250717-0001`) |

Your [`Sample`](api/samples/models.py:30) table references projects via:

```python
project_id: str = Field(foreign_key="project.project_id")  # ← FK to the STRING column
```

This means the FK relationship chain looks like:

```
sample.project_id  ──FK──►  project.project_id  (string, unique)
                             project.id          (uuid, PK — unused by sample)
```

The gap analysis question is: **should `Sample.project_id` point to `project.id` (the UUID PK) instead?**

---

## Key Concepts for Context

### What is a Foreign Key?

A foreign key is a column in one table that references a column in another table. The database enforces that the value in the FK column *must* exist in the referenced column. This is called **referential integrity** — you cannot have a sample pointing to a project that does not exist.

### What is a Natural Key vs a Surrogate Key?

- **Natural key**: A value that has real-world meaning. Your `project_id` string like `P-20250717-0001` is a natural key — humans can read it, it encodes a date, it appears in URLs and AWS Batch job names.
- **Surrogate key**: A value with no business meaning, generated purely for database use. Your UUID `id` is a surrogate key — it is random, opaque, and meaningless to a human.

### What does your FK currently do?

Your string FK `Sample.project_id → Project.project_id` is a **natural key FK**. It works correctly! The database enforces referential integrity because `project.project_id` has a `UNIQUE` constraint. Any unique column can serve as an FK target — it does not have to be the primary key.

---

## Option A: Keep the String FK (Current State)

### How it works

```
sample table                         project table
┌──────────┬────────────────────┐    ┌──────────┬────────────────────┬──────┐
│ id (PK)  │ project_id (FK)    │    │ id (PK)  │ project_id (UNIQUE)│ name │
├──────────┼────────────────────┤    ├──────────┼────────────────────┼──────┤
│ uuid-aaa │ P-20250717-0001    │───►│ uuid-111 │ P-20250717-0001    │ Proj │
│ uuid-bbb │ P-20250717-0001    │───►│          │                    │      │
│ uuid-ccc │ P-20250718-0001    │───►│ uuid-222 │ P-20250718-0001    │ Proj2│
└──────────┴────────────────────┘    └──────────┴────────────────────┘──────┘
```

### Pros

1. **Human-readable queries** — When you look at the `sample` table directly (in a DB client, logs, or debug output), you immediately see which project a sample belongs to without needing a JOIN:
   ```sql
   SELECT * FROM sample WHERE project_id = 'P-20250717-0001';
   -- vs.
   SELECT * FROM sample WHERE project_id = 'a3f8c1d2-7e4b-...';
   ```

2. **API simplicity** — The current API routes and services pass `project_id` strings everywhere. Routes like `GET /projects/{project_id}/samples` use the human-readable string directly. No translation layer needed between what the API receives and what the database stores:
   ```python
   # Current: the route param IS the FK value
   sample = Sample(sample_id="SAMP-001", project_id="P-20250717-0001")
   ```

3. **No migration needed** — It already works. The FK constraint is enforced. Referential integrity is intact. Zero risk.

4. **Natural alignment with external systems** — The `project_id` string is used in S3 paths (`s3://bucket/P-20250717-0001/`), AWS Batch job names (`vendor-ingestion-P-20250717-0001`), and OpenSearch indexes. Having the same value in the sample table means one less lookup when correlating across systems.

5. **Simpler code** — [`add_sample_to_project()`](api/project/services.py:534) can just do `Sample(project_id=project.project_id)` without needing to resolve the UUID first. Queries like [`get_project_samples()`](api/project/services.py:589) filter directly with `Sample.project_id == project.project_id`.

### Cons

1. **String comparison is slower than UUID comparison** — String indexes are larger (a `P-YYYYMMDD-NNNN` string is ~16 bytes as text vs 16 bytes as a native UUID binary). For small datasets this is negligible; it starts to matter at millions of rows.

2. **If `project_id` ever changes, the FK breaks** — If you were to rename a project's `project_id` (e.g. fixing a typo), you would need to update every sample row that references it. With a UUID FK, the internal `id` never changes, so renaming `project_id` would be a single-row update. *However: your current [`generate_project_id()`](api/project/services.py:43) auto-generates these and there is no rename API, so this risk is currently theoretical.*

3. **Inconsistency with the rest of the schema** — Every other FK in the codebase uses UUIDs:
   - [`SampleAttribute.sample_id`](api/samples/models.py:22) → `sample.id` (UUID)
   - [`ProjectAttribute.project_id`](api/project/models.py:21) → `project.id` (UUID)
   - [`FileSample.sample_id`](api/files/models.py:93) → `sample.id` (UUID)
   - [`QCMetricSample.sample_id`](api/qcmetrics/models.py:73) → `sample.id` (UUID)
   
   The string FK on `Sample.project_id` is the **only** FK in the entire schema that uses a natural key instead of the surrogate UUID. This inconsistency can confuse future developers.

4. **Dual-identity confusion** — The column name `project_id` appears on `Sample` but refers to the *string* business identifier, while the same column name `project_id` on `ProjectAttribute` refers to the *UUID* primary key. Same name, different types, different target columns.

---

## Option B: Migrate to UUID FK

### How it would work

```
sample table                         project table
┌──────────┬────────────────────┐    ┌──────────┬────────────────────┬──────┐
│ id (PK)  │ project_id (FK)    │    │ id (PK)  │ project_id (UNIQUE)│ name │
├──────────┼────────────────────┤    ├──────────┼────────────────────┼──────┤
│ uuid-aaa │ uuid-111           │───►│ uuid-111 │ P-20250717-0001    │ Proj │
│ uuid-bbb │ uuid-111           │───►│          │                    │      │
│ uuid-ccc │ uuid-222           │───►│ uuid-222 │ P-20250718-0001    │ Proj2│
└──────────┴────────────────────┘    └──────────┴────────────────────┘──────┘
```

The model would change to:

```python
class Sample(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sample_id: str
    project_id: uuid.UUID = Field(foreign_key="project.id")  # ← UUID FK now
```

### Pros

1. **Schema consistency** — Every FK in the system would use UUID surrogate keys. New developers see one pattern.

2. **Immutable reference** — UUIDs never change. If you add a project rename feature later, no cascade needed.

3. **Standard relational practice** — Most relational database textbooks recommend FKs point to the primary key. ORMs are optimized for this pattern. SQLModel/SQLAlchemy relationship loading works most naturally with PK-based FKs.

4. **Index performance at scale** — UUID comparisons using native binary type are faster than variable-length string comparisons. B-tree indexes on fixed-width columns are more compact.

### Cons

1. **Breaking change** — This requires an Alembic data migration that:
   - Adds a new `project_uuid` column to `sample`
   - Populates it by joining `sample.project_id → project.project_id → project.id`
   - Drops the old FK constraint
   - Drops the old `project_id` string column (or renames it)
   - Renames `project_uuid` → `project_id`
   - Adds new FK constraint to `project.id`
   - Requires a maintenance window for production data

2. **Loss of human readability** — The `sample` table alone no longer tells you which project a sample belongs to. You need a JOIN:
   ```sql
   -- Before: glance at the table and know
   SELECT * FROM sample;  -- project_id = 'P-20250717-0001'

   -- After: need a JOIN
   SELECT s.*, p.project_id FROM sample s JOIN project p ON s.project_id = p.id;
   ```

3. **API layer changes** — Every place that currently creates a sample with a string project_id would need to resolve the UUID first:
   ```python
   # Before
   sample = Sample(sample_id="SAMP-001", project_id="P-20250717-0001")

   # After
   project = session.exec(select(Project).where(Project.project_id == "P-20250717-0001")).first()
   sample = Sample(sample_id="SAMP-001", project_id=project.id)
   ```
   This affects [`add_sample_to_project()`](api/project/services.py:534), [`resolve_or_create_sample()`](api/samples/services.py:21), [`get_project_samples()`](api/project/services.py:589), and more.

4. **Public API response changes** — [`SamplePublic.project_id`](api/samples/models.py:53) currently returns the human-readable string. After migration, you would either:
   - Return the UUID (breaking API consumers)
   - Add a separate lookup to return the string (extra code + query)
   - Rename the field (e.g., `project_uuid` internally, keep `project_id` in the response model via a computed field)

5. **Ripple effects** — [`QCRecord.project_id`](api/qcmetrics/models.py:144) is also a plain string (not even an FK). [`FileCreate.project_id`](api/files/models.py:338) accepts strings. The string project_id is deeply woven through the codebase. Changing it in one place creates pressure to change it everywhere for consistency.

---

## Side-by-Side Summary

| Dimension | String FK (current) | UUID FK (proposed) |
|-----------|--------------------|--------------------|
| Referential integrity | ✅ Enforced | ✅ Enforced |
| Human readability | ✅ Direct | ❌ Requires JOIN |
| Schema consistency | ❌ Only string FK in system | ✅ Matches all other FKs |
| Rename safety | ⚠️ Would need cascading update | ✅ UUID never changes |
| Index performance | ⚠️ Slightly larger/slower | ✅ Fixed-width binary |
| Migration effort | ✅ None (already done) | ❌ Breaking data migration |
| Code simplicity | ✅ No resolution step | ❌ Must resolve string→UUID |
| API compatibility | ✅ No changes | ❌ Response model changes |
| Scale concern threshold | ~millions of rows | N/A |

---

## Recommendation

**For your current stage: keep the string FK and defer the migration.**

The reasoning:

1. **Referential integrity is already enforced.** The string FK works correctly — the database prevents orphaned samples. The "problem" this migration solves is aesthetic/conventional, not functional.

2. **The project_id is system-generated and immutable.** Since [`generate_project_id()`](api/project/services.py:43) auto-generates the value and there is no rename API, the main risk of natural key FKs (the referenced value changing) does not apply today.

3. **The migration has real cost and risk.** It touches the sample table (which is a core entity), requires coordinated changes across services/routes/models/tests, and needs a maintenance window for production data.

4. **There are higher-value items ahead.** Phase 2 (File Association Evolution) and Phase 3 (QC Multi-Entity Extension) deliver new capabilities. The string→UUID FK migration delivers only schema cleanliness.

**If you do decide to migrate later** (Phase 4 in the gap analysis), the right approach would be:

1. Rename the column in the model to something like `project_ref` (UUID FK to `project.id`)
2. Keep `project_id` as a read-only property that resolves the string via the relationship
3. Write a data migration that does the lookup and populates the new column
4. Update service layers to use the ORM relationship instead of the string column
5. Keep the public API response (`SamplePublic.project_id`) returning the human-readable string via the relationship

This preserves both API compatibility and schema correctness.
