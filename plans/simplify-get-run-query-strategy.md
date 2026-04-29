# Simplify GET Run Query Strategy

## The Core Question
If we have `original_barcode`, why are we parsing barcodes and normalizing `run_number` at all? We could just query by `original_barcode` directly.

## Current Architecture (Main + Our Merge)

### How GET /runs/{barcode} Works:
1. User requests: `GET /runs/20260202_SH00862_0012_BFLOWCELL99`
2. `get_run()` calls `parse_barcode("20260202_SH00862_0012_BFLOWCELL99")`
3. `parse_barcode()` strips padding: `run_number = str(int("0012"))` → "12"
4. Query: `WHERE run_date=... AND machine_id=... AND run_number="12" AND flowcell_id=...`
5. **Problem**: If DB has `run_number="0012"` (padded), query fails → 404

### Required Client Coordination:
- ✅ `runs_cp.sh` - Already strips padding (line 92: `$((10#$_run_number))`)
- ⚠️ `collectRunMetrics lambda` - Needs update to strip padding
- 🔄 All future clients must strip padding or GET fails

### Complexity:
- Clients must parse and normalize
- API must parse and normalize
- Tests must validate normalization
- Risk of padding mismatches causing 404s

---

## Alternative Architecture (Simpler)

### How GET /runs/{barcode} Would Work:
1. User requests: `GET /runs/20260202_SH00862_0012_BFLOWCELL99`
2. `get_run()` queries: `WHERE original_barcode = "20260202_SH00862_0012_BFLOWCELL99"`
3. Done! Exact match, no parsing needed.

### Fallback for Legacy Runs:
```python
def get_run(session: Session, run_barcode: str):
    # Try exact match on original_barcode first (fast)
    run = session.exec(
        select(SequencingRun).where(
            SequencingRun.original_barcode == run_barcode
        )
    ).one_or_none()
    
    if run:
        return run
    
    # Fallback: parse and query fields (for legacy runs without original_barcode)
    (run_date, run_time, machine_id, run_number, flowcell_id) = (
        SequencingRun.parse_barcode(run_barcode)
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

### Client Requirements:
- Send `original_barcode` with exact sequencer output
- Send `run_number` in ANY format (padded/unpadded doesn't matter)
- No parsing or normalization needed

### Benefits:
- ✅ **Simpler**: No normalization logic needed anywhere
- ✅ **Robust**: No risk of padding mismatches
- ✅ **Exact**: original_barcode is the natural key for lookups
- ✅ **Flexible**: Clients don't need to coordinate on run_number format
- ✅ **Performant**: Single indexed column lookup (with DB index)

### Trade-offs:
- Need DB index on `original_barcode` for performance
- Two-query pattern for legacy runs (rare)
- Collaborator's normalization work becomes less critical (but still useful for data consistency)

---

## Recommendation

**Adopt the Alternative Architecture:**

1. **API Change**: Update `get_run()` to query `original_barcode` first, fallback to field parsing
2. **DB Index**: Add index on `original_barcode` column
3. **Client Simplification**: 
   - Keep `runs_cp.sh` as-is (already sends original_barcode)
   - Keep lambda as-is (already sends original_barcode, NO need to strip padding)
4. **Migration Path**: Works for both new runs (with original_barcode) and legacy runs (without)

### Why This Is Better:
- The `original_barcode` column was designed to solve the exact problem we're trying to solve with normalization
- Querying the natural key is simpler and more maintainable than parsing + normalizing
- Eliminates coordination burden across clients
- `run_number` can be stored in any format for backward compatibility or internal use

### What About Normalization?
Keep it for **internal consistency** but not for **lookups**:
- Normalized `run_number` is still useful for sorting, filtering, or internal logic
- But for GET by barcode, use `original_barcode` as the source of truth
