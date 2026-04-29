# Fix Destructive Project Attribute Update

## Problem

When a user exports an RNA-Seq type project, the NGS-BMS worker sends a PUT request with
`{"attributes": [{"key": "xpress_project_id", "value": "-1"}]}`. In the new codebase,
`update_project()` in `api/project/services.py` (lines 279-298) performs a **delete-all-then-insert**
strategy for attributes. This means submitting a single attribute wipes every other attribute
on the project — a regression from the old behavior where updating one attribute did not destroy others.

### Root Cause

```python
# api/project/services.py lines 279-298 (current code)
# Delete all existing attributes for this project  ← DESTRUCTIVE
existing_attributes = session.exec(
    select(ProjectAttribute).where(
        ProjectAttribute.project_id == project.id
    )
).all()
for existing_attr in existing_attributes:
    session.delete(existing_attr)
```

### Example

A project has attributes `[{project_type: "RNA-Seq"}, {pi: "Dr. Smith"}]`.
The worker sends `PUT /projects/{id}` with `{"attributes": [{"key": "xpress_project_id", "value": "-1"}]}`.
**Current behavior:** `project_type` and `pi` are deleted; only `xpress_project_id` remains.
**Expected behavior:** `project_type` and `pi` are preserved; `xpress_project_id` is added.

### Correct Pattern Already Exists

`update_sample_in_project()` in the same file (line 791) already implements the correct
merge/upsert pattern for a single attribute — check if the key exists, update if so, create if not,
leave other attributes untouched.

## Solution: Merge/Upsert Strategy

Replace the delete-all/replace-all block in `update_project()` with an upsert loop:

```python
# Handle attributes if provided (merge/upsert - does NOT remove unmentioned attributes)
if update_request.attributes is not None and len(update_request.attributes) > 0:
    # Prevent duplicate keys in the request
    seen = set()
    keys = [attr.key for attr in update_request.attributes]
    dups = [k for k in keys if k in seen or seen.add(k)]
    if dups:
        raise HTTPException(...)

    for attr in update_request.attributes:
        existing_attr = session.exec(
            select(ProjectAttribute).where(
                ProjectAttribute.project_id == project.id,
                ProjectAttribute.key == attr.key,
            )
        ).first()

        if existing_attr:
            existing_attr.value = attr.value   # Update existing key
        else:
            session.add(ProjectAttribute(      # Insert new key
                project_id=project.id,
                key=attr.key,
                value=attr.value,
            ))
```

### Design Decision: Empty Attributes List

Sending `{"attributes": []}` is treated as a **no-op** — existing attributes are preserved.
There is no use case for bulk-deleting all attributes on a project.

## Files Changed

| File | Change |
|------|--------|
| `api/project/services.py` | Replace lines 268-298 with merge/upsert loop |
| `tests/api/test_projects.py` | Update 3 existing tests, add 2 new tests |

## Test Changes

| Test | Action |
|------|--------|
| `test_update_project_attributes` (line 341) | Rewrite: verify `Priority` is **preserved** when not in update payload, `Department` is updated, `Status` is added |
| `test_update_project_replaces_all_attributes` (line 458) | Rename to `test_update_project_merges_attributes` — verify only mentioned keys change, `Status` key is retained |
| `test_update_project_removes_all_attributes` (line 491) | Rewrite: verify sending `{"attributes": []}` is a **no-op** and existing attributes remain |
| *new* `test_update_project_merge_preserves_existing` | PUT with a single new attribute key; verify all original attributes still present |
| *new* `test_update_project_upsert_existing_key` | PUT with one existing key with new value; verify only that key value changes, others untouched |
| `test_update_project_with_empty_data` (line 435) | No change needed — already tests `{}` (no `attributes` field) → no change |

## Checklist

- [ ] Change `update_project()` in `api/project/services.py` to use merge/upsert strategy
- [ ] Update `test_update_project_attributes` to verify merge behavior
- [ ] Rewrite `test_update_project_replaces_all_attributes` to verify merge behavior
- [ ] Rewrite `test_update_project_removes_all_attributes` to verify empty list is a no-op
- [ ] Add `test_update_project_merge_preserves_existing`
- [ ] Add `test_update_project_upsert_existing_key`
- [ ] Verify `test_update_project_with_empty_data` still passes
- [ ] Run full test suite to confirm no regressions
