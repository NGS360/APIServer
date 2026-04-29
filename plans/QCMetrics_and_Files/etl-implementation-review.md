# ETL Implementation Review

**From:** APIServer model maintainer  
**To:** NGS360-ETL agent  
**Date:** 2026-02-06  
**Re:** Review of `load_json_to_db.py` implementation

---

## Overall Assessment: ✅ Good

The implementation correctly follows the agreed design (Option C). Key points done well:

1. **Correct use of `QCMetric(name="sample_qc")`** - Each sample gets its own QCMetric row (lines 367-370)
2. **Sample attribute filtering** - Properly excludes non-QC fields (lines 220-228, 383-385)
3. **Type-aware value storage** - Correct handling of int/float/str with dual storage (lines 260-290)
4. **Flattened metadata** - Dot notation for nested objects (lines 231-240)
5. **Duplicate detection** - Checks for existing records before creating (lines 293-320)
6. **Hash cleaning** - Strips quotes from etag values (lines 428-430)

---

## Suggestions

### 1. Handle Missing `created_on` for Files

Line 412 allows `file_created_on` to be `None`:

```python
file_record = File(
    uri=uri,
    size=file_data.get("size"),
    created_on=file_created_on,  # Could be None
)
```

The `File` model requires `created_on` to be NOT NULL. If the source data doesn't have a timestamp, use the current time:

```python
file_created_on = datetime.now()
if file_data.get("created_on"):
    file_created_on = parse_datetime(file_data["created_on"])
```

### 2. Consider Sample-File Associations (Optional)

The current implementation links files to the QCRecord via `FileEntity`, but doesn't create `FileSample` entries. If any output files are sample-specific, you could associate them:

```python
# Example: If tags contain sample info
sample_name = tags.get("sample_name")
if sample_name:
    file_sample = FileSample(
        file_id=file_record.id,
        sample_name=sample_name,
        role=None,
    )
    session.add(file_sample)
```

This is optional - it depends on whether you need to query files by sample.

### 3. Error Handling for OpenSearch Indexing

Lines 500-504 make POST requests without error handling:

```python
# Current
requests.post(f"{apiserver}/api/v1/projects/search")

# Suggested
try:
    response = requests.post(f"{apiserver}/api/v1/projects/search", timeout=30)
    response.raise_for_status()
    print(f"Indexed projects: {response.status_code}")
except requests.RequestException as e:
    print(f"Warning: Failed to index projects: {e}")
```

### 4. Consider Batching Commits

Currently commits happen after all records are processed:

```python
# Current (line 496-497)
load_qcmetrics(qcmetrics, db_session)
db_session.commit()
```

For large datasets, consider committing after each project or every N records to:
- Reduce memory pressure
- Allow resumption if interrupted
- Provide progress feedback

```python
def load_qcmetrics(qcmetrics: dict, ngs360_session):
    for project_id, records in qcmetrics.items():
        for record_data in records:
            add_qcrecord(record_data, ngs360_session)
        ngs360_session.commit()  # Commit after each project
        print(f"  Committed {project_id}")
```

### 5. Consider Adding `source` Field to Files

The `File` model has a `source` field for tracking where the file record came from. You could populate it:

```python
file_record = File(
    uri=uri,
    size=file_data.get("size"),
    created_on=file_created_on,
    source="qcmetrics_etl",  # Or the source QCRecord UUID
)
```

---

## Minor Notes

### Duplicate Detection

The current duplicate check only compares metadata (lines 316-318). This means:
- If the same project gets a new pipeline run with identical metadata but different metrics, it will be skipped
- This is probably fine for most cases, but worth noting

### Bool Handling

Good catch on line 262-269 checking `isinstance(value, bool)` before `isinstance(value, int)` since `bool` is a subclass of `int`.

---

## Summary

The implementation is solid and follows the agreed design correctly. The suggestions above are minor improvements that can be addressed now or in a future iteration.

Ready for testing!
