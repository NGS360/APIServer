# QCMetrics Model Recommendations

**From:** APIServer model maintainer  
**To:** NGS360-ETL agent  
**Date:** 2026-02-06  
**Re:** Response to design questions in `qcmetrics-etl-design.md`

---

## Summary

After reviewing the ETL design document and discussing with the stakeholder, we will:

1. **Modify the schema (Option C)** - Remove the unique constraint on `(qcrecord_id, name)` to allow multiple QCMetric rows with the same name, differentiated by their sample associations
2. **Omit sample attributes** - ASSAYMETHOD, SEX, SPECTYPE, etc. should NOT be stored in QCMetrics; rely on the Sample entity
3. **Use consistent metric naming** - Use `sample_qc` for per-sample QC metrics (not prefixed with sample name)

---

## Schema Change: Option C (Normalized)

### Current Constraint (Being Removed)

```python
# api/qcmetrics/models.py - QCMetric class
__table_args__ = (
    UniqueConstraint("qcrecord_id", "name", name="uq_qcmetric_record_name"),
)
```

### New Design

Remove the unique constraint entirely. Multiple `QCMetric` rows can have the same `name` within a `QCRecord`, differentiated by their `QCMetricSample` associations.

```
QCRecord(project_id="P-00000000-0001")
├── QCMetric(name="sample_qc")  -- for human1
│   ├── QCMetricSample(sample_name="human1", role=null)
│   └── QCMetricValue(key="QC_ForwardReadCount", value=1000000)
│   └── QCMetricValue(key="QC_FractionReadsAligned", value=0.98)
│
├── QCMetric(name="sample_qc")  -- for human2
│   ├── QCMetricSample(sample_name="human2", role=null)
│   └── QCMetricValue(key="QC_ForwardReadCount", value=950000)
│   └── QCMetricValue(key="QC_FractionReadsAligned", value=0.96)
│
├── QCMetric(name="somatic_variants")  -- paired analysis
│   ├── QCMetricSample(sample_name="tumor1", role="tumor")
│   ├── QCMetricSample(sample_name="normal1", role="normal")
│   └── QCMetricValue(key="tmb", value=8.5)
│   └── QCMetricValue(key="snv_count", value=15234)
│
└── QCMetric(name="pipeline_summary")  -- workflow-level
    └── QCMetricValue(key="total_samples_processed", value=48)
    └── (no QCMetricSample entries)
```

### Query Patterns

All sample-based queries use a consistent JOIN pattern:

```sql
-- Find all metrics for sample "human1"
SELECT qm.*, qms.sample_name, qms.role
FROM qcmetric qm
JOIN qcmetricsample qms ON qm.id = qms.qc_metric_id
WHERE qms.sample_name = 'human1';

-- Find all "sample_qc" metrics for a project
SELECT qm.*, qms.sample_name
FROM qcmetric qm
JOIN qcmetricsample qms ON qm.id = qms.qc_metric_id
JOIN qcrecord qr ON qm.qcrecord_id = qr.id
WHERE qm.name = 'sample_qc' AND qr.project_id = 'P-00000000-0001';

-- Find workflow-level metrics (no sample association)
SELECT qm.*
FROM qcmetric qm
LEFT JOIN qcmetricsample qms ON qm.id = qms.qc_metric_id
WHERE qms.id IS NULL;
```

### Indexes Required

The `QCMetricSample` table should have indexes on:
- `qc_metric_id` (for JOINs) - already implied by foreign key
- `sample_name` (for filtering by sample)

```sql
CREATE INDEX ix_qcmetricsample_sample_name ON qcmetricsample(sample_name);
```

---

## Metric Naming Convention

| Metric Type | Name | QCMetricSample Entries |
|-------------|------|------------------------|
| Per-sample QC | `sample_qc` | One entry per sample, role=null |
| Workflow-level | `pipeline_summary` | None |
| Paired analysis | `somatic_variants`, `germline_variants`, etc. | Multiple entries with roles |

**Important:** Do NOT encode the sample name in the metric name. Use `sample_qc`, not `sample_qc:human1` or `human1_sample_qc`.

---

## Sample Attributes: Omit from QCMetrics

The following fields from the source data should be **excluded** during ETL:

| Field | Reason |
|-------|--------|
| `samplename` | Used for QCMetricSample association, not stored as a value |
| `ASSAYMETHOD` | Sample attribute - belongs in Sample table |
| `SEX` | Sample attribute - belongs in Sample table |
| `SPECTYPE` | Sample attribute - belongs in Sample table |
| `STUDYID` | Sample attribute - belongs in Sample table |
| `USUBJID` | Sample attribute - belongs in Sample table |
| `VENDORNAME` | Sample attribute - belongs in Sample table |

### ETL Implementation

```python
SAMPLE_ATTRIBUTES = {
    "samplename",
    "ASSAYMETHOD",
    "SEX",
    "SPECTYPE",
    "STUDYID",
    "USUBJID",
    "VENDORNAME",
}

def transform_sample_metrics(sample_data: dict) -> dict:
    """Transform one sample's metrics to QCMetric format."""
    sample_name = sample_data["samplename"]
    
    values = {}
    for key, value in sample_data.items():
        if key in SAMPLE_ATTRIBUTES:
            continue  # Skip - belongs in Sample entity
        values[key] = value
    
    return {
        "name": "sample_qc",
        "samples": [{"sample_name": sample_name, "role": None}],
        "values": values,
    }
```

---

## Data Type Handling

Use the type-aware storage in `QCMetricValue`:

```python
def create_metric_value(key: str, value: Any) -> dict:
    """Convert a Python value to QCMetricValue fields."""
    if isinstance(value, int):
        return {
            "key": key,
            "value_string": str(value),
            "value_numeric": float(value),
            "value_type": "int"
        }
    elif isinstance(value, float):
        return {
            "key": key,
            "value_string": str(value),
            "value_numeric": value,
            "value_type": "float"
        }
    else:  # string or other
        return {
            "key": key,
            "value_string": str(value),
            "value_numeric": None,
            "value_type": "str"
        }
```

This enables:
- Numeric queries: `WHERE value_numeric > 0.95`
- String matching: `WHERE value_string = 'FR'`
- Type-aware display: Return as int/float/str based on `value_type`

---

## Complete ETL Transformation Example

```python
def transform_qcrecord(source: dict) -> dict:
    """Transform Elasticsearch QCRecord to relational model format."""
    
    # 1. Core QCRecord fields
    result = {
        "project_id": source["projectid"],
        "created_on": source["created_on"],
        "created_by": source["created_by"],
    }
    
    # 2. Pipeline metadata (flatten nested objects)
    metadata = {}
    for key, value in flatten_dict(source.get("metadata", {})).items():
        metadata[key] = str(value)
    result["metadata"] = metadata
    
    # 3. Sample-level metrics
    metrics = []
    for sample_data in source.get("sample_level_metrics", []):
        metrics.append(transform_sample_metrics(sample_data))
    result["metrics"] = metrics
    
    # 4. Output files (see file_model_unification.md)
    output_files = []
    for file_data in source.get("output_files", []):
        output_files.append(transform_output_file(file_data))
    result["output_files"] = output_files
    
    return result
```

---

## Schema Migration Required

The APIServer will need to update the Alembic migration to:

1. Remove the unique constraint `uq_qcmetric_record_name` from `qcmetric` table
2. Add index on `qcmetricsample.sample_name`

This change will be made before merging the QCMetrics branch.

---

## Questions?

If you encounter additional edge cases or have questions about specific data patterns, please update this document or create a new one in the plans directory.
