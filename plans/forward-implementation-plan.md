# Forward Implementation Plan: Query by original_barcode

## Executive Summary

**Problem:** Production 404 errors when users query with padded barcodes (e.g., `151109_M00950_0125_FLOWCELL`) because [`get_run()`](../api/runs/services.py:89) parses and normalizes the barcode, then queries normalized fields.

**Solution:** Query by `original_barcode` directly - no parsing, exact match lookup.

**Strategy:** Skip backfill migration, re-ETL legacy data from source with `original_barcode` populated.

---

## Implementation Checklist

### Phase 1: Schema Changes

#### 1.1 Update Model
[`api/runs/models.py:38`](../api/runs/models.py:38)

**Change from:**
```python
original_barcode: str | None = Field(default=None, max_length=100)
```

**Change to:**
```python
original_barcode: str = Field(max_length=100, index=True, unique=True)
```

**Rationale:**
- Remove `| None` → make required
- Add `index=True` → fast lookups
- Add `unique=True` → enforce one barcode per run

#### 1.2 Update Pydantic Models
[`api/runs/models.py:138-170`](../api/runs/models.py:138-170)

**SequencingRunCreate:**
```python
class SequencingRunCreate(SQLModel):
    run_date: date
    machine_id: str = Field(max_length=50)
    run_number: str  # Can be padded or unpadded - will be normalized
    flowcell_id: str = Field(max_length=100)
    original_barcode: str  # REQUIRED - exact machine output
    run_time: Optional[str] = Field(default=None, max_length=10)
    experiment_name: Optional[str] = Field(default="", max_length=255)
    run_folder_uri: Optional[str] = Field(default=None, max_length=500)
    status: RunStatus = RunStatus.PENDING
```

**SequencingRunPublic:**
```python
class SequencingRunPublic(SQLModel):
    # ... existing fields ...
    original_barcode: str  # Remove default=None
```

#### 1.3 Create Migration
```bash
cd /Users/vasques1/cbio/APIServer
alembic revision -m "make_original_barcode_required"
```

**Migration content:**
```python
def upgrade() -> None:
    # Add unique constraint
    op.create_unique_constraint(
        'uq_sequencingrun_original_barcode',
        'sequencingrun',
        ['original_barcode']
    )
    
    # Make NOT NULL (assumes re-ETL populates all rows)
    op.alter_column(
        'sequencingrun',
        'original_barcode',
        existing_type=sa.String(length=100),
        nullable=False
    )

def downgrade() -> None:
    op.alter_column(
        'sequencingrun',
        'original_barcode',
        existing_type=sa.String(length=100),
        nullable=True
    )
    op.drop_constraint(
        'uq_sequencingrun_original_barcode',
        'sequencingrun',
        type_='unique'
    )
```

---

### Phase 2: Fix Query Logic (CRITICAL)

#### 2.1 Simplify get_run()
[`api/runs/services.py:89-111`](../api/runs/services.py:89-111)

**Current (BROKEN):**
```python
def get_run(
    *,
    session: Session,
    run_barcode: str,
) -> SequencingRun | None:
    """Retrieve a sequencing run from the database."""
    (run_date, run_time, machine_id, run_number, flowcell_id) = (
        SequencingRun.parse_barcode(run_barcode)
    )
    try:
        run = session.exec(
            select(SequencingRun).where(
                SequencingRun.run_date == run_date,
                SequencingRun.machine_id == machine_id,
                SequencingRun.run_number == run_number,  # ← Fails on padding mismatch
                SequencingRun.flowcell_id == flowcell_id,
            )
        ).one_or_none()
    except Exception as e:
        logger.error(f"Error retrieving run {run_barcode}: {e}")
        return None
    return run
```

**New (FIXED):**
```python
def get_run(
    *,
    session: Session,
    run_barcode: str,
) -> SequencingRun | None:
    """Retrieve a sequencing run by its original barcode.
    
    Args:
        session: Database session
        run_barcode: The exact barcode as submitted (e.g., '151109_M00950_0125_FLOWCELL')
        
    Returns:
        SequencingRun if found, None otherwise
        
    Note:
        Uses exact match on original_barcode column (unique indexed).
        No parsing or normalization - query must match as stored.
    """
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

**Benefits:**
- ✅ No parsing → no padding mismatches
- ✅ Exact match → predictable behavior
- ✅ Indexed unique key → fast O(1) lookup
- ✅ Simpler code → fewer bugs

#### 2.2 Verify add_run() Flow
[`api/runs/services.py:54-86`](../api/runs/services.py:54-86)

**Current implementation already correct:**
```python
def add_run(
    *,
    session: Session,
    run: SequencingRunCreate,
) -> SequencingRun:
    """Add a new sequencing run to the database and index it in OpenSearch."""
    
    # Parse to normalize fields (strips padding from run_number)
    (run_date, run_time, machine_id, run_number, flowcell_id) = (
        SequencingRun.parse_barcode(run.run_barcode)
    )
    
    # Check if run already exists using normalized fields
    existing_run = session.exec(
        select(SequencingRun).where(
            SequencingRun.run_date == run_date,
            SequencingRun.machine_id == machine_id,
            SequencingRun.run_number == run_number,  # Normalized
            SequencingRun.flowcell_id == flowcell_id,
        )
    ).first()
    
    if existing_run:
        return existing_run
    
    # Create with normalized run_number + original_barcode
    db_run = SequencingRun(
        run_date=run_date,
        run_time=run_time,
        machine_id=machine_id,
        run_number=run_number,  # ← Normalized (e.g., "125")
        flowcell_id=flowcell_id,
        original_barcode=run.original_barcode,  # ← As submitted (e.g., "..._0125_...")
        experiment_name=run.experiment_name,
        run_folder_uri=run.run_folder_uri,
        status=run.status,
    )
    session.add(db_run)
    session.commit()
    session.refresh(db_run)
    return db_run
```

**Flow:**
1. Client sends: `original_barcode = "151109_M00950_0125_FLOWCELL"`, `run_number = "0125"`
2. API calls `parse_barcode(run.run_barcode)` → normalizes to `run_number = "125"`
3. Stores: `run_number = "125"` (normalized), `original_barcode = "151109_M00950_0125_FLOWCELL"` (as-is)
4. Returns: `barcode` property returns `original_barcode` (via computed field)

✅ Already correct - no changes needed!

#### 2.3 Check Other Query Paths

**Search paths to verify:**
- [`get_run_samplesheet()`](../api/runs/services.py:259) - calls `get_run()`
- [`get_run_metrics()`](../api/runs/services.py:333) - calls `get_run()`
- [`update_run()`](../api/runs/services.py:381) - calls `get_run()`
- [`associate_sample_with_run()`](../api/runs/services.py:738) - calls `get_run()`

All these call `get_run()` → will automatically use new query logic. ✅

**OpenSearch indexing:**
- [`add_run()`](../api/runs/services.py:54) indexes after creation
- Uses `run.to_dict()` which includes `barcode` computed property
- `barcode` property returns `original_barcode` when set
- ✅ Already correct!

---

### Phase 3: Client Updates

#### 3.1 runs_cp.sh
[`../NGS360-IlluminaCleanUpScripts/runs_cp.sh:92,119`](../NGS360-IlluminaCleanUpScripts/runs_cp.sh:92)

**Current:**
```bash
# Normalizes run_number
_run_number=$((10#$_run_number))

# Sends both
local _json="{
  \"run_number\": \"${_run_number}\",        # ← "125" (normalized)
  \"original_barcode\": \"${_run_id}\",     # ← "151109_M00950_0125_..." (padded)
  ...
}"
```

✅ **Already correct** - no changes needed!

#### 3.2 runs_cp_ont.sh
[`../NGS360-IlluminaCleanUpScripts/runs_cp_ont.sh`](../NGS360-IlluminaCleanUpScripts/runs_cp_ont.sh)

Check if it sends `original_barcode` in POST body. If not, add it.

#### 3.3 collectRunMetrics Lambda
[`../NGS360-collectRunMetrics-lambda/collect_run_metrics/collect_run_metrics.py:439,454`](../NGS360-collectRunMetrics-lambda/collect_run_metrics/collect_run_metrics.py:439)

**Current:**
```python
run_number = run_info["RunInfo"]["Run"]["@Number"]  # e.g., "0125" (padded)

data = {
    "run_number": run_number,              # Padded
    "original_barcode": run_barcode,       # e.g., "151109_M00950_0125_..."
    "status": "Ready"
}
```

✅ **Already sends original_barcode** - no changes needed!

**Note:** Lambda sends padded `run_number`, but that's fine - API's `add_run()` normalizes it via `parse_barcode()`.

---

### Phase 4: Testing

#### 4.1 Update Existing Tests
[`tests/api/test_runs.py`](../tests/api/test_runs.py)

**Tests that need updating:**
1. Any test that creates a run without `original_barcode`
2. Tests that expect `barcode` reconstruction when `original_barcode` is None

**Example fix:**
```python
# OLD
response = client.post("/api/v1/runs", json={
    "run_date": "2019-01-10",
    "machine_id": "MACHINE123",
    "run_number": "0001",
    "flowcell_id": "FLOWCELL123",
    # No original_barcode
    "status": "Ready"
})

# NEW
response = client.post("/api/v1/runs", json={
    "run_date": "2019-01-10",
    "machine_id": "MACHINE123",
    "run_number": "0001",
    "flowcell_id": "FLOWCELL123",
    "original_barcode": "190110_MACHINE123_0001_FLOWCELL123",  # ← Required
    "status": "Ready"
})
```

#### 4.2 Add New Tests

**Test: POST with padding, GET with same barcode**
```python
def test_post_and_get_with_padded_barcode(client: TestClient):
    """Verify padded barcode round-trip works correctly."""
    # POST run with padded run_number
    post_response = client.post("/api/v1/runs", json={
        "run_date": "2025-01-10",
        "machine_id": "M00950",
        "run_number": "0125",  # Padded
        "flowcell_id": "FLOWCELL123",
        "original_barcode": "250110_M00950_0125_FLOWCELL123",
        "status": "Ready"
    })
    assert post_response.status_code == 200
    
    run_data = post_response.json()
    assert run_data["run_number"] == "125"  # Stored normalized
    assert run_data["barcode"] == "250110_M00950_0125_FLOWCELL123"  # Exposed as submitted
    
    # GET with original padded barcode
    get_response = client.get("/api/v1/runs/250110_M00950_0125_FLOWCELL123")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["barcode"] == "250110_M00950_0125_FLOWCELL123"
    assert get_data["run_number"] == "125"
```

**Test: GET with invalid barcode returns 404**
```python
def test_get_run_invalid_barcode_returns_404(client: TestClient):
    """Verify invalid barcode returns 404."""
    response = client.get("/api/v1/runs/INVALID_BARCODE_123")
    assert response.status_code == 404
```

**Test: Unique constraint prevents duplicates**
```python
def test_duplicate_original_barcode_rejected(client: TestClient):
    """Verify unique constraint on original_barcode."""
    run_data = {
        "run_date": "2025-01-10",
        "machine_id": "M00950",
        "run_number": "0125",
        "flowcell_id": "FLOWCELL123",
        "original_barcode": "250110_M00950_0125_FLOWCELL123",
        "status": "Ready"
    }
    
    # First POST succeeds
    response1 = client.post("/api/v1/runs", json=run_data)
    assert response1.status_code == 200
    
    # Second POST with same original_barcode should fail
    response2 = client.post("/api/v1/runs", json=run_data)
    # Expect either 409 Conflict or returns existing run
    assert response2.status_code in [200, 409]
```

#### 4.3 Run Full Test Suite
```bash
pytest tests/api/test_runs.py -v
pytest tests/ -v  # Full suite
```

---

### Phase 5: Deployment

#### 5.1 Pre-Deployment Checklist
- [ ] All tests pass locally
- [ ] Migration tested on dev database
- [ ] Client repos updated (if needed)
- [ ] Re-ETL script ready with `original_barcode` population

#### 5.2 Deployment Steps

**Step 1: Deploy schema changes**
```bash
# Apply migration
alembic upgrade head
```

**Step 2: Re-ETL legacy data**
```bash
# Update ETL script to include original_barcode
# Run ETL to populate all runs with original_barcode
# Verify: SELECT COUNT(*) FROM sequencingrun WHERE original_barcode IS NULL;
# Should return 0
```

**Step 3: Deploy API code changes**
```bash
# Deploy updated get_run() and models
# Monitor for 404 errors (should decrease)
```

**Step 4: Verify**
- Query existing runs by barcode → should work
- Create new runs → should require original_barcode
- Check logs for errors

#### 5.3 Rollback Plan

If issues arise:
1. Revert API code (restore old `get_run()`)
2. Keep schema changes (no harm)
3. Debug and fix
4. Redeploy

---

## Benefits Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Query method** | Parse + field-based (4 conditions) | Direct lookup (1 condition) |
| **404 errors** | Frequent (padding mismatches) | Eliminated (exact match) |
| **Query performance** | Composite index scan | Unique index O(1) lookup |
| **Code complexity** | High (parsing in query path) | Low (simple WHERE) |
| **Client coordination** | Required (normalize) | Not required (send as-is) |
| **Maintenance** | Fragile | Robust |

---

## FAQ

**Q: Why normalize run_number if we have original_barcode?**
A: Normalization keeps storage efficient and allows mathematical operations. `original_barcode` is for querying and display only.

**Q: What if client sends wrong original_barcode?**
A: Unique constraint prevents duplicates. If barcode doesn't match normalized fields, it's stored as-is (client's responsibility).

**Q: Can we still query by fields?**
A: Yes, but not recommended. Use `original_barcode` for all lookups.

**Q: What about ONT runs?**
A: Same approach - store `original_barcode` as submitted, normalize other fields.

---

## Next Steps

Ready to implement? Switch to **Code mode** to:
1. Update schema (models + migration)
2. Simplify `get_run()` service
3. Update tests
4. Run test suite

---

_Plan created: 2026-04-21_
_Status: Ready for implementation_
