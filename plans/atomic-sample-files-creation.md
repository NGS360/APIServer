# Atomic Sample + Files Creation

## Context

Backend workers (e.g. samplesheet-driven ingest) need to create samples **and** attach
file records in a single atomic API call. Today this requires N+1 calls:
1 bulk sample creation + N separate `POST /api/files` calls.

This plan extends the existing bulk and single sample creation endpoints to
accept an optional `files` array per sample, creating `File`, `FileSample`,
`FileProject`, `FileHash`, and `FileTag` records in the same transaction.

## Design Decisions

| Decision | Choice |
|---|---|
| Endpoints affected | Both `POST /projects/{pid}/samples` and `POST /projects/{pid}/samples/bulk` |
| File dedup strategy | Hash-aware: if URI already linked to sample and hashes match (or no hashes provided), skip; if hashes differ, create new version |
| SamplePublic response | Keep clean — no file counts. Single endpoint silently creates files. |
| Bulk response | Add `files_created` and `files_skipped` to both per-item and aggregate response |
| Helper placement | `_create_sample_files()` in `api/samples/services.py` |

## File Dedup Algorithm

```
For each SampleFileInput:
  1. Query for existing File linked to sample via FileSample with same URI
  2. If no existing file → CREATE
  3. If existing file found:
     a. Input has no hashes → SKIP (assume identical)
     b. Input has hashes → compare all provided hashes against FileHash records
        - All match → SKIP
        - Any mismatch or missing → CREATE new version
```

## Model Changes (api/samples/models.py)

### New: SampleFileInput
```python
class SampleFileInput(SQLModel):
    """File to create and associate with a sample during sample creation."""
    uri: str
    tags: dict[str, str] | None = None
    hashes: dict[str, str] | None = None
    role: str | None = None
    source: str | None = None
    original_filename: str | None = None
    size: int | None = None
    storage_backend: str | None = None
```

### Modified: SampleCreate
Add `files: List[SampleFileInput] | None = None`

### Modified: BulkSampleItemResponse
Add `files_created: int = 0` and `files_skipped: int = 0`

### Modified: BulkSampleCreateResponse
Add `files_created: int = 0` and `files_skipped: int = 0`

## Service Changes

### New helper: _create_sample_files (api/samples/services.py)

```python
def _create_sample_files(
    session: Session,
    sample: Sample,
    project_uuid: uuid.UUID,
    file_inputs: List[SampleFileInput],
) -> tuple[int, int]:  # (created, skipped)
```

For each SampleFileInput:
1. Check for existing File linked to sample via FileSample with matching URI
2. If found, apply hash-aware dedup
3. If creating: File + FileProject + FileSample + FileHash + FileTag records

### Modified: bulk_create_samples (api/samples/services.py)
After run association block, call `_create_sample_files()` per sample.
Accumulate `files_created` and `files_skipped` in per-item and aggregate.

### Modified: add_sample_to_project (api/project/services.py)
After run association, call `_create_sample_files()` if `sample_in.files`.
No response change (SamplePublic stays clean).

## Example Request

```json
{
  "samples": [
    {
      "sample_id": "SAMP001",
      "run_barcode": "240315_M00001_0042_HXXXXXXXXX",
      "attributes": [{"key": "Tissue", "value": "Liver"}],
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
    }
  ]
}
```

## Test Plan (tests/api/test_bulk_samples.py)

1. Bulk with files — happy path
2. Bulk idempotent resubmission — no hashes → files skipped
3. Bulk idempotent resubmission — matching hashes → files skipped
4. Hash mismatch → new file version created
5. Mixed samples — some with files, some without
6. Single sample with files — POST /projects/{pid}/samples
7. Single sample file dedup
