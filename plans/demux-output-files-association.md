# Demux Output Files: Association Strategy

> **Status:** Open for discussion — deferred from Phase 3b implementation  
> **Date:** 2025-03-06  
> **Context:** Run-scoped QCRecords for demux stats

## Problem

When a demux pipeline produces fastqs and submits a run-scoped QCRecord with `output_files`, those files are currently associated **only** via `FileQCRecord` (role="output"). They are **not** associated with the `SequencingRun` via `FileSequencingRun`.

This creates a gap in the re-demux cleanup path:

```
clear_samples_for_run()
  └─ queries FileSequencingRun to find files to delete
       └─ MISSES files linked only via FileQCRecord
```

## Current State

### What exists (infrastructure)

| Junction Table | Docstring Roles | Created by |
|---|---|---|
| `FileSequencingRun` | samplesheet, stats, interop, runinfo | Files API (direct creation) |
| `FileWorkflowRun` | input, output, log, intermediate | Files API (direct creation) |
| `FileQCRecord` | output, log, report | QCMetrics API (`_create_file_for_qcrecord()`) |

### What happens today for demux

- `submit_demux_job()` submits an AWS Batch job — **fire-and-forget**
- No callback or post-demux step registers produced fastqs
- Files currently in `FileSequencingRun` are input/metadata (samplesheet, Stats.json)
- Demux output files (fastqs) are **not stored** in the database

### How QCRecord output_files work

`_create_file_for_qcrecord()` (api/qcmetrics/services.py:243) creates:
1. A `File` record
2. A `FileQCRecord` junction row (role="output")

It does **not** create a `FileSequencingRun` junction row.

## Options

### Option A: Dual-associate output files for run-scoped QCRecords

When creating output files for a run-scoped QCRecord, also create a `FileSequencingRun` junction row linking the file to the SequencingRun.

**Implementation:** ~3 lines in `_create_file_for_qcrecord()`:

```python
# If QCRecord is run-scoped, also associate file with the SequencingRun
if sequencing_run_id:
    session.add(FileSequencingRun(
        file_id=file_record.id,
        sequencing_run_id=sequencing_run_id,
        role="output",
    ))
```

**Pros:**
- `clear_samples_for_run()` finds them automatically via `FileSequencingRun`
- Files are queryable by both run barcode AND QCRecord ID
- Correctly models reality: these files belong to both the run and the QCRecord
- Cascade delete from either direction works

**Cons:**
- Two junction rows per file (minor storage overhead)
- Must pass `sequencing_run_id` through to `_create_file_for_qcrecord()`

### Option B: Extend cleanup to walk QCRecord → FileQCRecord → File

In the re-demux cleanup (todo #31), after deleting run-scoped QCRecords, rely on cascade deletes to clean up `FileQCRecord` → `File`.

**Implementation:** When deleting QCRecords in cleanup, SQLAlchemy cascades on `FileQCRecord` handle it:

```python
# After finding run-scoped QCRecords for this run:
for qcrecord in run_scoped_records:
    session.delete(qcrecord)  # cascades to FileQCRecord rows
    # But does NOT cascade to File — FileQCRecord cascade is on the File side
```

**Problem:** The cascade direction is wrong. `FileQCRecord` has `cascade="all, delete-orphan"` on the **File** side (deleting a File cascades to FileQCRecord), not the QCRecord side. Deleting a QCRecord does NOT automatically delete the File records.

This would require explicit file cleanup:
```python
for qcrecord in run_scoped_records:
    file_assocs = session.exec(
        select(FileQCRecord).where(FileQCRecord.qcrecord_id == qcrecord.id)
    ).all()
    for fqr in file_assocs:
        file_record = session.get(File, fqr.file_id)
        if file_record:
            session.delete(file_record)
    session.delete(qcrecord)
```

**Pros:**
- No dual-association complexity
- Files belong to exactly one entity

**Cons:**
- Requires explicit file cleanup code in the re-demux path
- Files not queryable by run barcode (only by QCRecord ID)
- More complex cleanup logic

### Option C: Demux fastqs are NOT QCRecord output_files

Fastqs from demux should be registered separately via the Files API with a `FileSequencingRun` association. The QCRecord only contains metrics (read counts, quality scores, etc.) — not the actual data files.

**Pros:**
- Clean separation: QCRecord = metrics, Files API = files
- No dual-association needed
- `clear_samples_for_run()` already handles `FileSequencingRun` cleanup

**Cons:**
- Requires two separate API calls from the demux pipeline (one for files, one for QCRecord)
- Loses the atomic "here are all my outputs" pattern that `output_files` provides

## Recommendation

**Option A (dual-associate)** is the recommended approach because:
1. It requires minimal code changes (~3 lines)
2. It makes files discoverable from both the run and QCRecord perspectives
3. The re-demux cleanup path already works via `FileSequencingRun`
4. It correctly models that demux output files belong to both entities

## Decision

**TBD** — to be discussed and decided before implementing demux pipeline integration.

> Note: This decision does NOT block Phase 3b implementation. The `output_files` field on `QCRecordCreate` already works for project-scoped records. The question is specifically about whether run-scoped records should dual-associate their output files.
