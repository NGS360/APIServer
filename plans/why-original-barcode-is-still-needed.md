# Why `original_barcode` is Still Needed After Merging Main

## Question
Since main's `parse_barcode()` strips zero-padding with `run_number = str(int(parts[2]))`, does this negate our `original_barcode` changes?

## Answer: NO - It Actually Proves Why We Need It!

The zero-padding stripping is a **data normalization strategy** - good for storage consistency. But it creates a search problem that ONLY `original_barcode` can solve.

---

## The Problem Flow

### Without `original_barcode` (main branch only):
```
Sequencer outputs:    20260202_SH00862_0012_ASC2144730-SC3
                      ↓
parse_barcode():      Strips padding → run_number="12"
                      Parses 8-char date → run_date=2026-02-02
                      ↓
Storage:              run_date=2026-02-02, run_number="12"
                      ↓
barcode property:     strftime("%y%m%d") → "260202"
                      int(run_number) → 12
                      Returns: "260202_SH00862_12_ASC2144730-SC3"
                      ↓
OpenSearch indexes:   "260202_SH00862_12_ASC2144730-SC3"
                      ^^^^^^          ^^
                      2-digit year    no padding

User searches:        "20260202_SH00862_0012_ASC2144730-SC3"
                      ^^^^^^^^        ^^^^
                      4-digit year    with padding

Result: NO MATCH ❌
```

### With `original_barcode` (our merged solution):
```
Sequencer outputs:    20260202_SH00862_0012_ASC2144730-SC3
                      ↓
parse_barcode():      Strips padding → run_number="12" (normalized!)
                      Parses 8-char date → run_date=2026-02-02
                      ↓
Storage:              run_date=2026-02-02, 
                      run_number="12" (normalized)
                      original_barcode="20260202_SH00862_0012_ASC2144730-SC3" (preserved!)
                      ↓
barcode property:     if original_barcode: return it
                      Returns: "20260202_SH00862_0012_ASC2144730-SC3"
                      ↓
OpenSearch indexes:   "20260202_SH00862_0012_ASC2144730-SC3"

User searches:        "20260202_SH00862_0012_ASC2144730-SC3"

Result: PERFECT MATCH ✅
```

---

## The Smart Barcode Property

```python
@computed_field
@property
def barcode(self) -> str:
    """Return original_barcode if stored, otherwise reconstruct from fields."""
    if self.original_barcode:
        return self.original_barcode  # ← EXACT sequencer output!
    return self._reconstruct_barcode()  # ← Fallback for legacy rows
```

This gives us **the best of both worlds**:
- Normalized storage (consistent run_number values)
- Original preservation (exact sequencer output for search/display)

---

## Why Both Changes Are Necessary

| Change | Purpose | What It Solves |
|--------|---------|----------------|
| **Collaborator's**: `parse_barcode()` date detection | Parse both YYMMDD and YYYYMMDD | Prevents ValueError crash |
| **Collaborator's**: `run_number = str(int(...))` | Normalize storage | Consistent data format |
| **Our Addition**: `original_barcode` column | Preserve exact input | Search works! |
| **Our Addition**: Smart `barcode` property | Return original when available | Users see what they typed |
| **Our Addition**: Client updates | Send `original_barcode` in POST | Capture at source |

---

## Legacy Compatibility

For OLD rows without `original_barcode`:
```python
def _reconstruct_barcode(self) -> str:
    """Fallback for backward compatibility."""
    if self.run_time is None:
        run_date = self.run_date.strftime("%y%m%d")  # 2-digit year
        run_number = int(self.run_number)  # No padding
        return f"{run_date}_{self.machine_id}_{run_number}_{self.flowcell_id}"
    # ONT reconstruction
    ...
```

This ensures old data still works, just without perfect search matching.

---

## Conclusion

The collaborator's zero-padding stripping **strengthens** our solution:
1. Normalizes data in the database (good practice)
2. Makes `original_barcode` preservation even more critical
3. Proves that reconstruction alone cannot solve the search problem
4. Validates our two-part approach: normalize + preserve

**Our `original_barcode` solution is the ONLY way to make search work correctly while maintaining normalized storage.**
