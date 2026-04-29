# Bulk File Creation Endpoint

## Context

Companion to [atomic-sample-files-creation.md](./atomic-sample-files-creation.md) which handles
files during sample creation. This plan originally proposed a **standalone bulk file creation
endpoint** for when samples already exist and files need to be attached after the fact.

**Use cases originally envisioned:**
- ETL backfill: samples were created earlier, files arrive later
- Re-running ETL when samples exist but files are missing
- Pipeline outputs that need to be registered against existing samples
- Any scenario where N files need to be created in one atomic API call

## Current State (Revised 2026-04-13)

### What already exists

Since the original plan was written, the codebase has gained substantial bulk
file creation capability through the **samples/bulk** endpoint:

| Capability | Endpoint | Status |
|---|---|---|
| Single file creation | `POST /api/files` | ✅ Implemented |
| Bulk sample + file creation | `POST /projects/{pid}/samples/bulk` | ✅ Implemented |
| Single sample + file creation | `POST /projects/{pid}/samples` | ✅ Implemented |
| Standalone bulk file creation | `POST /api/files/bulk` | ❌ Not implemented |

#### `POST /projects/{project_id}/samples/bulk` ([route](api/project/routes.py:217))

This endpoint, implemented in [`bulk_create_samples()`](api/samples/services.py:363), already
handles the primary demux worker scenario:

- Accepts a list of samples, each with optional `files: List[SampleFileInput]`
- Each sample can include `run_barcode` for `SampleSequencingRun` association
- Files get: `File` + `FileSample` + `FileProject` + `FileHash` + `FileTag` records
- **Hash-aware dedup** via [`_create_sample_files()`](api/samples/services.py:245):
  same URI + matching hashes → skip; different hashes → new version
- **Idempotent**: re-submitting the same batch reuses existing samples/associations
- **Atomic**: all-or-nothing transaction
- Response includes per-item and aggregate `files_created` / `files_skipped` counts

#### `POST /api/files` ([route](api/files/routes.py:36))

Single-file creation via [`FileCreate`](api/files/models.py:398) supports:

- Entity associations: `project_id`, `sequencing_run_id`, `qcrecord_id`,
  `workflow_run_id`, `pipeline_id`
- Sample associations: `samples: List[SampleInput]` (resolved via
  [`resolve_or_create_sample()`](api/samples/services.py:26))
- Hashes, tags, and all metadata
- Validator: at least one entity association required (no orphan files)
- Validator: `project_id` required when samples are provided

### Demux worker use case: ALREADY SUPPORTED ✅

A client worker that demultiplexes sequencing runs and needs to add files to a
group of samples in that run can use the existing bulk samples endpoint:

```json
POST /api/v1/projects/{project_id}/samples/bulk

{
  "samples": [
    {
      "sample_id": "SAMP001",
      "run_barcode": "240315_M00001_0042_HXXXXXXXXX",
      "files": [
        {
          "uri": "s3://bucket/project/P-123/SAMP001_R1.fastq.gz",
          "tags": {"read": "R1", "format": "fastq.gz"},
          "hashes": {"md5": "abc123"},
          "role": "tumor"
        },
        {
          "uri": "s3://bucket/project/P-123/SAMP001_R2.fastq.gz",
          "tags": {"read": "R2", "format": "fastq.gz"},
          "hashes": {"md5": "def456"}
        }
      ]
    },
    {
      "sample_id": "SAMP002",
      "run_barcode": "240315_M00001_0042_HXXXXXXXXX",
      "files": [
        {
          "uri": "s3://bucket/project/P-123/SAMP002_R1.fastq.gz",
          "hashes": {"md5": "ghi789"}
        },
        {
          "uri": "s3://bucket/project/P-123/SAMP002_R2.fastq.gz",
          "hashes": {"md5": "jkl012"}
        }
      ]
    }
  ]
}
```

This single call atomically:
1. Creates or reuses samples `SAMP001` and `SAMP002`
2. Associates both samples with the sequencing run
3. Creates all 4 file records with `FileSample` + `FileProject` associations
4. Stores hashes and tags
5. Is fully idempotent on re-submission

**Test coverage** for this flow exists in
[`TestBulkSampleWithFiles`](tests/api/test_bulk_samples.py:633) with 7 tests
covering: happy path, idempotent resubmission (with and without hashes),
hash mismatch versioning, mixed samples with/without files, and backward
compatibility.

## Gap Analysis: When is `POST /api/files/bulk` still needed?

The existing sample-centric bulk endpoint covers the demux use case, but there
are scenarios where a standalone files bulk endpoint would be more appropriate:

| Scenario | Sample-centric bulk | Standalone files bulk |
|---|---|---|
| Demux: per-sample fastqs | ✅ Natural fit | Possible but indirect |
| Run-level files (Stats.json, InterOp) | ❌ No sample to attach to | ✅ Better fit |
| Pipeline outputs (project or workflow-run scoped) | ❌ Wrong endpoint | ✅ Better fit |
| ETL backfill: files for existing samples, no project context | ❌ Requires project_id | ✅ Would use FileCreate.samples |
| Files associated with QCRecords | ❌ Not supported | ✅ via qcrecord_id |

### Verdict

The standalone `POST /api/files/bulk` endpoint is **not needed for the immediate
demux worker use case**. It remains a nice-to-have for future non-sample-scoped
bulk file registration. Deprioritize in favor of other work.

## Original Design (preserved for future reference)

If/when this endpoint is needed, the design below remains valid.

### Endpoint: `POST /api/files/bulk`

| Decision | Choice |
|---|---|
| Request model | Wraps existing `FileCreate` in a list |
| Transaction | Atomic — all files succeed or none |
| Dedup strategy | URI-based: if File with same URI exists, skip creation but ensure FileSample link |
| Response | Per-item detail + aggregate counts |
| Auth | Same as existing `POST /api/files` — no special auth required |

### Model Changes (api/files/models.py)

```python
class BulkFileCreateRequest(SQLModel):
    """Request body for POST /api/files/bulk."""
    files: List[FileCreate]

    @field_validator('files')
    @classmethod
    def files_must_not_be_empty(cls, v: List[FileCreate]) -> List[FileCreate]:
        if not v:
            raise ValueError('files list must not be empty')
        return v


class BulkFileItemResponse(SQLModel):
    """Per-item detail in the bulk file creation response."""
    uri: str
    file_id: uuid.UUID
    created: bool       # True if new file created, False if URI already existed


class BulkFileCreateResponse(SQLModel):
    """Aggregate response for the bulk file creation endpoint."""
    files_created: int
    files_existing: int
    items: List[BulkFileItemResponse]
```

### Service: `create_files_bulk()`

```python
def create_files_bulk(
    session: Session,
    bulk_request: BulkFileCreateRequest,
) -> BulkFileCreateResponse:
    """
    Create multiple file records in a single atomic transaction.

    For each FileCreate in the request:
    1. Check if a File with the same URI already exists
    2. If yes: skip creation, report created=False
       - But still ensure FileSample links exist for any samples listed
    3. If no: create File + FileHash + FileTag + FileSample + entity associations
    4. Commit all-or-nothing
    """
```

**Key difference from single `create_file()`:** The bulk version does NOT call
`session.commit()` per file. Instead, it flushes after each file (to get UUIDs)
and commits once at the end.

### Route registration note

This route must be registered **before** the `/{file_id}` route to avoid
FastAPI treating 'bulk' as a file_id parameter.

### Test Plan

1. Happy path — Create 2 new files with sample associations → both created
2. Idempotent resubmission — Submit same files again → both skipped, FileSample links intact
3. Mixed new and existing — 1 new file + 1 existing URI → 1 created, 1 skipped
4. Empty list — Validation error
5. Missing project_id with samples — Validation error from FileCreate validator
6. Sample resolution — File references non-existent sample → auto-created stub
7. FileSample link for existing file — File exists but not linked to sample → link added
8. Entity associations — File with project_id creates FileProject row
