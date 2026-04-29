# Support for 4-Digit Year Illumina Barcodes

## Problem Statement

Newer Illumina sequencers emit run barcodes with 4-digit years (YYYYMMDD format) instead of the legacy 2-digit years (YYMMDD). For example:
- **Old format**: `190110_MACHINE123_0001_FLOWCELL123` (YYMMDD)
- **New format**: `20260202_SH00862_0012_ASC2144730-SC3` (YYYYMMDD)

The original implementation hardcoded `%y%m%d` for Illumina 4-field barcodes, causing a 500 error:
```
ValueError: unconverted data remains: 0202
```

Additionally, even if parsing succeeded, the system would reconstruct barcodes using `%y%m%d`, causing:
1. **Search failures**: OpenSearch indexed `260202_SH00862_...` but users searched `20260202_SH00862_...`
2. **Display inconsistency**: API returned reconstructed 6-char barcodes instead of original 8-char barcodes

## Solution Overview

The fix has two components:

### 1. Parse Both Date Formats
Detect date field length (6 vs 8 chars) and use the appropriate `strptime` format:
```python
date_str = run_id_fields[0]
date_fmt = "%Y%m%d" if len(date_str) == 8 else "%y%m%d"
```

### 2. Preserve Original Barcode
Store the exact barcode from the sequencer in a new `original_barcode` column:
- When set, the `barcode` computed property returns `original_barcode`
- When NULL (legacy rows), `_reconstruct_barcode()` generates barcode from fields
- OpenSearch indexes the original barcode, ensuring search works correctly

## Implementation Details

### APIServer Changes

#### Models ([`api/runs/models.py`](../api/runs/models.py))
1. **New column**: `original_barcode: str | None = Field(default=None, max_length=100)`
2. **Updated `parse_barcode()`** (line 62):
   - Detects 6-char vs 8-char date field
   - Wrapped `strptime` in `try/except ValueError`
   - Updated docstring to document both formats
3. **New `_reconstruct_barcode()`** (line 108): Backward compatibility for legacy rows
4. **Updated `barcode` computed property** (line 122): Prefers `original_barcode` when set
5. **Added to `SequencingRunCreate`** (line 162): Optional `original_barcode` field
6. **Added to `SequencingRunPublic`** (line 200): Optional `original_barcode` field with `= None` default

#### API Endpoints
Updated all `SequencingRunPublic` construction sites to pass `original_barcode`:
- [`api/runs/routes.py`](../api/runs/routes.py) line 64: `add_run()`
- [`api/runs/services.py`](../api/runs/services.py) lines 133, 361: `get_runs()`, `update_run()`
- [`api/project/services.py`](../api/project/services.py) line 215: `get_project_by_project_id()`

#### Database Migration
Auto-generated Alembic migration [`5d121c106e1a`](../alembic/versions/5d121c106e1a_add_original_barcode_to_sequencingrun.py):
```sql
ALTER TABLE sequencingrun ADD COLUMN original_barcode VARCHAR(100) NULL;
```

#### Tests ([`tests/api/test_runs.py`](../tests/api/test_runs.py))
Added 11 new tests across 3 test classes:
- **`TestParseBarcodeFormats`** (line 1730): 5 tests for 6-digit, 8-digit, ONT, invalid, too-few-fields
- **`TestOriginalBarcodeProperty`** (line 1774): 3 tests for barcode property logic
- **`TestOriginalBarcodeEndToEnd`** (line 1812): 3 tests for create/retrieve with original_barcode
- Updated `test_search_runs` (line 551) to include `original_barcode` in expected response

All 461 tests pass with no regressions.

### Client Repos

#### NGS360-IlluminaCleanUpScripts

##### [`runs_cp.sh`](../NGS360-IlluminaCleanUpScripts/runs_cp.sh)
Updated `upsert_run()`:
1. **Date parsing** handles both 6 and 8-char dates:
   ```bash
   if [ ${#_run_date} -eq 8 ]; then
       _year="${_run_date:0:4}"; _month="${_run_date:4:2}"; _day="${_run_date:6:2}"
   else
       _year="20${_run_date:0:2}"; _month="${_run_date:2:2}"; _day="${_run_date:4:2}"
   fi
   ```
2. **POST body** includes `"original_barcode": "${_run_id}"`

##### [`runs_cp_ont.sh`](../NGS360-IlluminaCleanUpScripts/runs_cp_ont.sh)
Updated `upsert_run()` POST body (line 111) to include `"original_barcode": "${_run_id}"`

#### NGS360-collectRunMetrics-lambda

##### [`collect_run_metrics.py`](../NGS360-collectRunMetrics-lambda/collect_run_metrics/collect_run_metrics.py)
Updated `add_run_to_ngs360()` POST body (line 459) to include:
```python
"original_barcode": run_barcode,
```
The `run_barcode` comes from `RunInfo.xml`'s `@Id` field (line 433).

## Backward Compatibility

### Existing Database Rows
Legacy rows with NULL `original_barcode` continue to work:
- `_reconstruct_barcode()` generates barcodes from component fields
- Illumina: `{YY}{MM}{DD}_{machine_id}_{run_number}_{flowcell_id}` (6-char date)
- ONT: `{YYYY}{MM}{DD}_{run_time}_{machine_id}_{flowcell_id}_{run_number}` (8-char date)

### Client Compatibility
All client repos now send `original_barcode` in POST bodies:
- Old Illumina runs: `original_barcode` with 6-char date
- New Illumina runs: `original_barcode` with 8-char date
- ONT runs: `original_barcode` with full 5-field format

The API accepts `original_barcode` as optional, so clients that don't send it (if any exist) will fall back to reconstruction.

## Deployment Notes

### Order of Deployment
1. **APIServer**: Deploy first with migration
2. **NGS360-IlluminaCleanUpScripts**: Deploy updated scripts
3. **NGS360-collectRunMetrics-lambda**: Deploy to `bugfix_flowcell_names` alias (for APIServer v1)

### Database Migration
Run after APIServer deployment:
```bash
alembic upgrade head
```

### Testing Checklist
- [ ] Verify 8-digit date barcodes parse without error
- [ ] Verify OpenSearch indexing preserves original barcode
- [ ] Verify UI search finds runs by original 8-digit barcode
- [ ] Verify legacy runs (NULL `original_barcode`) still work
- [ ] Verify Illumina sync scripts create runs with `original_barcode`
- [ ] Verify ONT sync scripts create runs with `original_barcode`
- [ ] Verify collectRunMetrics Lambda creates runs with `original_barcode`

## Git Commits

### APIServer
**Branch**: `bugfix-accept-illumina-4-digit-year`  
**Commit**: `3a9b892`  
**Message**: "fix: support 4-digit year Illumina barcodes and preserve original_barcode"

### NGS360-IlluminaCleanUpScripts
**Branch**: `master`  
**Commit**: `9f036c9`  
**Message**: "fix: support 4-digit year Illumina barcodes and send original_barcode"

### NGS360-collectRunMetrics-lambda
**Branch**: `bugfix_flowcell_names` (for APIServer v1)  
**Commit**: `4156dad`  
**Message**: "fix: send original_barcode when creating runs in NGS360"

## Related Context

### Historical Note
The collaborator mentioned commit `7c2bde7` ("Add GET /runs/{barcode}"), which renamed `parse_runid` to `parse_barcode` but **did not fix the date format issue**. That commit only changed method/parameter names; the `strptime` calls remained hardcoded to `%y%m%d` for Illumina and `%Y%m%d` for ONT.

### Why ONT Wasn't Affected
ONT barcodes have 5 fields (vs 4 for Illumina), triggering a separate code path that already used `%Y%m%d`. The bug only affected Illumina's 4-field branch.
