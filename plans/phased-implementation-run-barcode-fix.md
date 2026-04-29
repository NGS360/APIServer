# Simplified Implementation: Run Barcode Query Fix

## Executive Summary

**Problem:** Production 404 errors when querying runs with padded barcodes due to normalization mismatches in [`get_run()`](../api/runs/services.py:89).

**Solution:** Replace field-based query in `get_run()` with direct `original_barcode` lookup. No fallback logic needed.

**Why simple?** Search is already broken, so no regression risk. Backfill ETL follows immediately after deploy, closing the legacy-run gap quickly. No throwaway code.

---

## What Changes (and What Doesn't)

| Component | Change? | Notes |
|-----------|---------|-------|
| [`get_run()`](../api/runs/services.py:89) | **Yes** | Replace parse + 4-field query with `WHERE original_barcode = ?` |
| [`add_run()`](../api/runs/services.py:54) | **No** | Duplicate check via `get_run(run.barcode)` works because new runs have `original_barcode` set |
| [`SequencingRun` model](../api/runs/models.py:25) | **No** | `original_barcode` field and `barcode` property already correct |
| [`SequencingRunCreate`](../api/runs/models.py:138) | **No** | Keep `original_barcode` optional for now; future PR makes it required |
| DB schema | **Yes** | Add unique index on `original_barcode` for non-NULL values |
| ETL backfill script | **Yes** | New script in `../NGS360-ETL/` to populate `original_barcode` from `runs.json` |

---

## Implementation

### 1. Alembic Migration: Add Unique Index

```python
def upgrade():
    op.create_index(
        'ix_sequencingrun_original_barcode',
        'sequencingrun',
        ['original_barcode'],
        unique=True,
        postgresql_where=sa.text('original_barcode IS NOT NULL'),
    )

def downgrade():
    op.drop_index('ix_sequencingrun_original_barcode', 'sequencingrun')
```

Partial unique index allows multiple NULLs for legacy rows while ensuring no duplicate `original_barcode` values for new rows.

### 2. Replace `get_run()` Query Logic

**Current** — [`api/runs/services.py:89-111`](../api/runs/services.py:89):
```python
def get_run(session, run_barcode):
    (run_date, run_time, machine_id, run_number, flowcell_id) = (
        SequencingRun.parse_barcode(run_barcode)  # ← normalizes, strips padding
    )
    run = session.exec(
        select(SequencingRun).where(
            SequencingRun.run_date == run_date,
            SequencingRun.machine_id == machine_id,
            SequencingRun.run_number == run_number,
            SequencingRun.flowcell_id == flowcell_id,
        )
    ).one_or_none()
    return run
```

**New** — direct lookup, no parsing:
```python
def get_run(session, run_barcode):
    """Retrieve a sequencing run by its original barcode."""
    try:
        run = session.exec(
            select(SequencingRun).where(
                SequencingRun.original_barcode == run_barcode
            )
        ).one_or_none()
    except Exception as e:
        logger.error(f"Error retrieving run {run_barcode}: {e}")
        return None
    return run
```

**Why no fallback?**
- All current clients already send `original_barcode` — [`runs_cp.sh`](../../NGS360-IlluminaCleanUpScripts/runs_cp.sh) and [`collectRunMetrics lambda`](../../NGS360-collectRunMetrics-lambda/collect_run_metrics/collect_run_metrics.py) both include it in POST
- Legacy runs get `original_barcode` populated by ETL backfill immediately after deploy
- The brief window where legacy runs lack `original_barcode` is acceptable since search is already broken
- No throwaway code to write then remove

### 3. Tests

**Test: query by original_barcode**
```python
def test_get_run_by_original_barcode(client):
    response = client.post("/api/v1/runs", json={
        "run_date": "2025-01-10",
        "machine_id": "M00950",
        "run_number": "0125",
        "flowcell_id": "FLOWCELL123",
        "original_barcode": "250110_M00950_0125_FLOWCELL123",
        "status": "Ready"
    })
    assert response.status_code == 200

    get_response = client.get("/api/v1/runs/250110_M00950_0125_FLOWCELL123")
    assert get_response.status_code == 200
    assert get_response.json()["barcode"] == "250110_M00950_0125_FLOWCELL123"
```

**Test: run without original_barcode returns 404**
```python
def test_get_run_without_original_barcode_returns_404(client, session):
    legacy_run = SequencingRun(
        run_date=datetime.date(2019, 1, 10),
        machine_id="MACHINE123",
        run_number="1",
        flowcell_id="FLOWCELL123",
        original_barcode=None,
        status="Ready",
    )
    session.add(legacy_run)
    session.commit()

    response = client.get("/api/v1/runs/190110_MACHINE123_0001_FLOWCELL123")
    assert response.status_code == 404  # Expected until backfill populates original_barcode
```

**Test: duplicate detection works for new runs**
```python
def test_duplicate_run_detected(client):
    run_data = {
        "run_date": "2025-01-10",
        "machine_id": "M00950",
        "run_number": "0125",
        "flowcell_id": "FLOWCELL123",
        "original_barcode": "250110_M00950_0125_FLOWCELL123",
        "status": "Ready"
    }
    response1 = client.post("/api/v1/runs", json=run_data)
    assert response1.status_code == 200

    response2 = client.post("/api/v1/runs", json=run_data)
    assert response2.status_code == 409
```

**Existing tests:** Update any test fixtures that create runs without `original_barcode` and then try to query them via `get_run()` — they'll need `original_barcode` set.

### 4. ETL Backfill Script (NGS360-ETL repo)

**File:** `../NGS360-ETL/backfill_original_barcode.py`

The [`runs.json`](../../NGS360-ETL/runs.json) already contains the original padded barcode in its `barcode` field alongside the normalized `run_number`:

```json
{
  "id": 6067,
  "run_date": "2015-11-09",
  "machine_id": "M00950",
  "run_number": "125",
  "flowcell_id": "000000000-AKDLF",
  "barcode": "151109_M00950_0125_000000000-AKDLF"
}
```

The script follows the same patterns as [`load_json_to_db.py`](../../NGS360-ETL/load_json_to_db.py) and [`backfill_sample_associations.py`](../../NGS360-ETL/backfill_sample_associations.py):

```python
#!/usr/bin/env python
"""
Backfill original_barcode for legacy SequencingRun rows from runs.json.

Reads runs.json, matches each entry to a DB row by composite key
using the same _run_cache_key pattern as load_json_to_db.py, and sets
original_barcode = barcode from the JSON.

Usage:
    PYTHONPATH=/path/to/APIServer python backfill_original_barcode.py --environment dev
    PYTHONPATH=/path/to/APIServer python backfill_original_barcode.py --environment dev --dry-run
"""
import argparse
import json
import os

from dotenv import load_dotenv
from sqlmodel import create_engine, Session, select

from api.runs.models import SequencingRun


def _run_cache_key(run_date, machine_id, run_number, flowcell_id):
    """Normalize composite key to strings — same as load_json_to_db.py."""
    return (str(run_date), str(machine_id), str(run_number), str(flowcell_id))


def backfill(session, runs_json_path, dry_run=False):
    """Match runs.json entries to DB rows and set original_barcode."""
    # Load runs.json
    with open(runs_json_path, "r", encoding="utf-8") as f:
        json_runs = json.load(f)
    print(f"Loaded {len(json_runs)} runs from {runs_json_path}")

    # Index JSON by composite key → original barcode
    json_index = {}
    for entry in json_runs:
        try:
            run_number_normalized = str(int(entry["run_number"]))
        except (ValueError, TypeError):
            continue
        key = _run_cache_key(
            entry["run_date"], entry["machine_id"],
            run_number_normalized, entry["flowcell_id"],
        )
        json_index[key] = entry["barcode"]

    # Fetch DB runs missing original_barcode
    db_runs = session.exec(
        select(SequencingRun).where(
            SequencingRun.original_barcode.is_(None)
        )
    ).all()
    print(f"Found {len(db_runs)} DB runs without original_barcode")

    stats = {"updated": 0, "not_found": 0, "already_set": 0}

    for run in db_runs:
        key = _run_cache_key(
            run.run_date, run.machine_id,
            run.run_number, run.flowcell_id,
        )
        original_barcode = json_index.get(key)

        if original_barcode:
            if dry_run:
                print(f"  [DRY RUN] {key} → {original_barcode}")
            else:
                run.original_barcode = original_barcode
                session.add(run)
            stats["updated"] += 1
        else:
            print(f"  WARNING: No JSON match for {key}")
            stats["not_found"] += 1

    if not dry_run:
        session.commit()

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Backfill complete:")
    print(f"  Updated: {stats['updated']}")
    print(f"  Not found in JSON: {stats['not_found']}")
    return stats


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill original_barcode from runs.json",
    )
    parser.add_argument(
        "--environment", choices=["dev", "staging", "prod"],
        required=True, help="Database environment",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show updates without committing",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    load_dotenv()

    db_setting = os.getenv(
        {"dev": "DATABASE_DEV", "staging": "DATABASE_STAGING",
         "prod": "DATABASE_PROD"}[args.environment]
    )
    print(f"Connecting to {args.environment}: {db_setting}")
    engine = create_engine(db_setting, echo=False)

    with Session(engine) as session:
        backfill(session, "runs.json", dry_run=args.dry_run)
```

**Key design decisions:**
- Uses the same [`_run_cache_key()`](../../NGS360-ETL/load_json_to_db.py:367) pattern as the existing ETL for consistent matching
- Normalizes `run_number` via `str(int(...))` to match what `load_runs()` stores
- Only touches rows where `original_barcode IS NULL` — safe to re-run
- Follows the same `--environment` / `--dry-run` CLI pattern as other ETL scripts

---

## Brief Gap During Deploy → Backfill

Between deploy and ETL backfill, legacy runs without `original_barcode` will not be individually queryable via `GET /runs/{barcode}`. This is acceptable because:

1. **Search is already broken** — users cannot find runs via search today
2. **Run listing works** — `GET /runs` still returns all runs with pagination
3. **New runs work immediately** — all current clients send `original_barcode`
4. **Gap closes quickly** — backfill ETL runs right after deploy

---

## Future PR: Enforce Requirement

After ETL backfill is verified and all `original_barcode` values are populated:

- [ ] Alembic migration: make `original_barcode` NOT NULL
- [ ] Model: `original_barcode: str = Field(max_length=100)` — remove `| None`
- [ ] [`SequencingRunCreate`](../api/runs/models.py:138): make `original_barcode` required
- [ ] Update unique index from partial to full
- [ ] Update API docs

---

## Rollback Plan

- Revert [`get_run()`](../api/runs/services.py:89) to field-based query
- Drop unique index
- No data loss — `original_barcode` column remains, just unused

---

## Implementation Checklist

**Schema (APIServer):**
- [ ] Create Alembic migration: partial unique index on `original_barcode`

**Code (APIServer):**
- [ ] Replace [`get_run()`](../api/runs/services.py:89) with `WHERE original_barcode = run_barcode` — no fallback, no `parse_barcode()`

**Tests (APIServer):**
- [ ] Test: new run with `original_barcode` → GET returns 200
- [ ] Test: run without `original_barcode` → GET returns 404
- [ ] Test: duplicate `original_barcode` → POST returns 409
- [ ] Update existing test fixtures to include `original_barcode` where `get_run()` is exercised
- [ ] Run full test suite — all tests pass

**ETL Script (NGS360-ETL):**
- [ ] Create `backfill_original_barcode.py` in `../NGS360-ETL/`
- [ ] Match DB runs to `runs.json` entries by composite key
- [ ] Set `original_barcode` from JSON `barcode` field
- [ ] Support `--dry-run` and `--environment` flags

**Deploy + Backfill:**
- [ ] Deploy APIServer to dev/staging
- [ ] Run `backfill_original_barcode.py --environment dev --dry-run` to verify
- [ ] Run `backfill_original_barcode.py --environment dev` to apply
- [ ] Verify: `SELECT COUNT(*) FROM sequencingrun WHERE original_barcode IS NULL` returns 0
- [ ] Test querying legacy runs by padded barcode
- [ ] Repeat for staging/prod

---

_Plan created: 2026-04-21_
_Status: Ready for implementation_
