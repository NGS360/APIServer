# Bulk OpenSearch Indexing Optimization

## Problem

When uploading a sample sheet with ~100 samples, the [`bulk_create_samples()`](api/samples/services.py:363) function calls [`add_object_to_index()`](api/search/services.py:65) **once per sample**. Each call makes:

1. A **PUT** to index the document ([line 83](api/search/services.py:83))
2. A **POST** to refresh the index ([line 84](api/search/services.py:84))

For 100 samples this produces **~200 HTTP requests** to OpenSearch, which is the primary bottleneck.

The same per-document pattern also affects [`reindex_samples()`](api/samples/services.py:227), which loops over every sample in the database and calls `add_object_to_index()` one at a time.

## Current State: Side-by-Side Comparison

| Entity | Reindex function | Uses bulk? | Resets index? |
|--------|-----------------|------------|---------------|
| Projects | [`reindex_projects()`](api/project/services.py:464) | ✅ `add_objects_to_index()` + `reset_index()` | ✅ Yes |
| Runs | [`reindex_runs()`](api/runs/services.py:233) | ✅ `add_objects_to_index()` + `reset_index()` | ✅ Yes |
| **Samples** | [`reindex_samples()`](api/samples/services.py:227) | ❌ loop + `add_object_to_index()` | ❌ Uses `delete_index()` — no recreate |

| Entity | Bulk-create function | Post-commit indexing |
|--------|---------------------|---------------------|
| **Samples** | [`bulk_create_samples()`](api/samples/services.py:363) | ❌ loop + `add_object_to_index()` per sample ([lines 549-556](api/samples/services.py:549)) |

## Root Cause: `add_object_to_index()` refreshes every call

```python
# api/search/services.py:65-84
def add_object_to_index(client, document, index):
    payload = {}
    for field in document.body.__searchable__:
        value = getattr(document.body, field)
        if value:
            payload[field] = getattr(document.body, field)

    client.index(index=index, id=str(document.id), body=payload)   # PUT
    client.indices.refresh(index=index)                              # POST — every single time
```

The existing bulk helper [`add_objects_to_index()`](api/search/services.py:15) already solves this — it uses `helpers.bulk()` and refreshes only once at the end. It just isn't being used everywhere it should be.

## Plan

### 1. Refactor `bulk_create_samples()` post-commit indexing to use `add_objects_to_index()`

**File:** [`api/samples/services.py`](api/samples/services.py:548)

Replace the per-sample loop:

```python
# BEFORE (lines 548-556)
if opensearch_client:
    for sample in newly_created_samples:
        session.refresh(sample)
        search_doc = SearchDocument(id=str(sample.id), body=sample)
        try:
            add_object_to_index(opensearch_client, search_doc, index="samples")
        except Exception:
            pass
```

With a single bulk call:

```python
# AFTER
if opensearch_client and newly_created_samples:
    search_docs = []
    for sample in newly_created_samples:
        session.refresh(sample)
        search_docs.append(SearchDocument(id=str(sample.id), body=sample))
    try:
        add_objects_to_index(opensearch_client, search_docs, index="samples")
    except Exception:
        pass  # best-effort indexing
```

This requires importing `add_objects_to_index` at [line 23](api/samples/services.py:23).

### 2. Refactor `reindex_samples()` to match project/run pattern

**File:** [`api/samples/services.py`](api/samples/services.py:227)

Replace:

```python
# BEFORE (lines 227-237)
def reindex_samples(session, client):
    delete_index(client, "samples")
    samples = session.exec(select(Sample)).all()
    for sample in samples:
        search_doc = SearchDocument(id=str(sample.id), body=sample)
        add_object_to_index(client, search_doc, index="samples")
```

With:

```python
# AFTER — matches reindex_projects() / reindex_runs()
def reindex_samples(session, client):
    samples = session.exec(select(Sample)).all()
    search_docs = [
        SearchDocument(id=str(s.id), body=s) for s in samples
    ]
    reset_index(client, "samples")
    add_objects_to_index(client, search_docs, "samples")
```

This also requires importing `reset_index` and `add_objects_to_index` at [line 23](api/samples/services.py:23).

### 3. Update imports in `api/samples/services.py`

**File:** [`api/samples/services.py`](api/samples/services.py:23)

```python
# BEFORE
from api.search.services import add_object_to_index, delete_index

# AFTER
from api.search.services import add_object_to_index, add_objects_to_index, delete_index, reset_index
```

Note: `add_object_to_index` is still needed for the single-sample [`add_sample_to_project()`](api/samples/services.py:127) path.

## Impact Summary

| Scenario | Before | After |
|----------|--------|-------|
| Bulk create 100 samples | ~200 HTTP requests to OpenSearch | 1 bulk request + 1 refresh |
| Reindex all samples | 2N requests — N index + N refresh | 1 bulk request + 1 refresh |
| Single sample create | 2 requests — unchanged | Unchanged |

## Files Modified

1. [`api/samples/services.py`](api/samples/services.py) — imports, `reindex_samples()`, `bulk_create_samples()`

No new files, no model changes, no test changes needed — the existing [`MockOpenSearchClient`](tests/conftest.py:20) in conftest already handles both `index()` and the patterns used by the bulk helper.
