"""
Services for the QCMetrics API.

Business logic for creating, searching, and deleting QC records.
"""

import logging
from datetime import datetime, timezone
import uuid as uuid_module
from fastapi import HTTPException, status
from sqlmodel import Session, select, col

from api.qcmetrics.models import (
    QCRecord,
    QCRecordMetadata,
    QCMetric,
    QCMetricValue,
    QCMetricSample,
    QCRecordCreate,
    QCRecordCreated,
    QCRecordPublic,
    QCRecordsPublic,
    MetadataKeyValue,
    MetricPublic,
    MetricValuePublic,
    MetricSamplePublic,
    MetricInput,
)
from api.files.models import (
    File,
    FileHash,
    FileTag,
    FileSample,
    FileQCRecord,
    FileCreate,
    FileSummary,
    HashPublic,
    TagPublic,
    FileSamplePublic,
)
from api.samples.services import resolve_or_create_sample
from api.samples.models import Sample
from api.runs.models import SequencingRun
from api.runs.services import get_run as get_sequencing_run


logger = logging.getLogger(__name__)


def _resolve_run_id_to_run(
    session: Session,
    run_id_str: str,
) -> SequencingRun:
    """
    Resolve a human-readable run_id string to a SequencingRun object.

    Raises HTTPException(422) if run_id doesn't match any run.
    """
    run = get_sequencing_run(session=session, run_id=run_id_str)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"SequencingRun not found for run_id: {run_id_str}"
        )
    return run


def create_qcrecord(
    session: Session,
    qcrecord_create: QCRecordCreate,
    created_by: str,
) -> QCRecordCreated:
    """
    Create a new QC record with all associated data.

    Supports two scoping modes:
    - project_id: project-scoped (e.g., alignment QC, variant QC)
    - sequencing_run_id: run-scoped (e.g., demux stats)

    Run ID strings are resolved to UUIDs at this layer.
    """
    # ── Resolve sequencing_run_id string → UUID ───────────────────
    resolved_run_uuid: uuid_module.UUID | None = None
    resolved_run_id_str: str | None = None
    if qcrecord_create.sequencing_run_id:
        run = _resolve_run_id_to_run(
            session, qcrecord_create.sequencing_run_id
        )
        resolved_run_uuid = run.id
        resolved_run_id_str = run.run_id

    # ── Check for duplicate record ────────────────────────────────
    existing = _check_duplicate_record(
        session, qcrecord_create, resolved_run_uuid
    )
    if existing:
        scope_label = (
            f"project {qcrecord_create.project_id}"
            if qcrecord_create.project_id
            else f"run {resolved_run_id_str}"
        )
        logger.info(
            "Equivalent QC record already exists for %s: %s",
            scope_label, existing.id
        )
        return QCRecordCreated(
            id=existing.id,
            created_on=existing.created_on,
            created_by=existing.created_by,
            project_id=existing.project_id,
            sequencing_run_id=resolved_run_id_str,
            is_duplicate=True,
        )

    # ── Validate project_id FK (only for project-scoped) ─────────
    if qcrecord_create.project_id:
        from api.project.models import Project
        project = session.exec(
            select(Project).where(
                Project.project_id == qcrecord_create.project_id
            )
        ).first()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Project not found: {qcrecord_create.project_id}"
                )
            )

    # ── Create main QC record ─────────────────────────────────────
    qcrecord = QCRecord(
        created_on=datetime.now(timezone.utc),
        created_by=created_by,
        project_id=qcrecord_create.project_id,
        sequencing_run_id=resolved_run_uuid,
        workflow_run_id=qcrecord_create.workflow_run_id,
    )
    session.add(qcrecord)
    session.flush()  # Get the ID

    # ── Add metadata ──────────────────────────────────────────────
    if qcrecord_create.metadata:
        for key, value in qcrecord_create.metadata.items():
            metadata_entry = QCRecordMetadata(
                qcrecord_id=qcrecord.id,
                key=key,
                value=str(value),
            )
            session.add(metadata_entry)

    # ── Add metrics ───────────────────────────────────────────────
    if qcrecord_create.metrics:
        for metric_input in qcrecord_create.metrics:
            _create_metric(
                session,
                qcrecord.id,
                metric_input,
                qcrecord_create.project_id,
            )

    # ── Add output files ──────────────────────────────────────────
    if qcrecord_create.output_files:
        for file_create in qcrecord_create.output_files:
            _create_file_for_qcrecord(
                session,
                qcrecord_id=qcrecord.id,
                file_create=file_create,
                project_id=qcrecord_create.project_id,
            )

    session.commit()
    session.refresh(qcrecord)

    scope_label = (
        f"project {qcrecord.project_id}"
        if qcrecord.project_id
        else f"run {resolved_run_id_str}"
    )
    logger.info(
        "Created QC record %s for %s by %s",
        qcrecord.id, scope_label, created_by
    )

    return QCRecordCreated(
        id=qcrecord.id,
        created_on=qcrecord.created_on,
        created_by=qcrecord.created_by,
        project_id=qcrecord.project_id,
        sequencing_run_id=resolved_run_id_str,
        workflow_run_id=qcrecord.workflow_run_id,
        is_duplicate=False,
    )


def _create_metric(
    session: Session,
    qcrecord_id,
    metric_input: MetricInput,
    project_id: str | None,
) -> QCMetric:
    """Create a metric group with its samples and values."""
    # Resolve sequencing_run_id string → UUID if provided
    sr_id = None
    if metric_input.sequencing_run_id:
        run = _resolve_run_id_to_run(
            session, metric_input.sequencing_run_id
        )
        sr_id = run.id

    wr_id = metric_input.workflow_run_id

    metric = QCMetric(
        qcrecord_id=qcrecord_id,
        name=metric_input.name,
        sequencing_run_id=sr_id,
        workflow_run_id=wr_id,
    )
    session.add(metric)
    session.flush()

    # Add sample associations (resolve sample_name → Sample.id via FK)
    if metric_input.samples:
        for sample_input in metric_input.samples:
            sample_name = (
                sample_input.sample_name if hasattr(sample_input, 'sample_name')
                else sample_input['sample_name']
            )
            role = (
                sample_input.role if hasattr(sample_input, 'role')
                else sample_input.get('role')
            )
            resolved_sample_id = resolve_or_create_sample(
                session=session,
                sample_name=sample_name,
                project_id=project_id,
            )
            sample_assoc = QCMetricSample(
                qc_metric_id=metric.id,
                sample_id=resolved_sample_id,
                role=role,
            )
            session.add(sample_assoc)

    # Add metric values with type preservation and dual storage
    for key, value in metric_input.values.items():
        # Determine the original type and numeric value
        if isinstance(value, bool):
            # bool is subclass of int, so check first
            value_type = "str"
            value_numeric = None
        elif isinstance(value, int):
            value_type = "int"
            value_numeric = float(value)  # Store as float for consistent numeric ops
        elif isinstance(value, float):
            value_type = "float"
            value_numeric = value
        else:
            value_type = "str"
            value_numeric = None

        metric_value = QCMetricValue(
            qc_metric_id=metric.id,
            key=key,
            value_string=str(value),
            value_numeric=value_numeric,
            value_type=value_type,
        )
        session.add(metric_value)

    return metric


def _create_file_for_qcrecord(
    session: Session,
    qcrecord_id,
    file_create: FileCreate,
    project_id: str,
) -> File:
    """Create a file record with its hashes, tags, samples, and QCRecord association."""
    file_record = File(
        uri=file_create.uri,
        size=file_create.size,
        created_on=file_create.created_on or datetime.now(timezone.utc),
    )
    session.add(file_record)
    session.flush()

    # Add typed QCRecord association (replaces polymorphic FileEntity)
    qcrecord_assoc = FileQCRecord(
        file_id=file_record.id,
        qcrecord_id=qcrecord_id,
        role="output",
    )
    session.add(qcrecord_assoc)

    # Add hashes (dictionary: {"algorithm": "value"})
    if file_create.hashes:
        for algorithm, value in file_create.hashes.items():
            hash_entry = FileHash(
                file_id=file_record.id,
                algorithm=algorithm,
                value=value,
            )
            session.add(hash_entry)

    # Add tags (dictionary: {"key": "value"})
    if file_create.tags:
        for key, value in file_create.tags.items():
            tag_entry = FileTag(
                file_id=file_record.id,
                key=key,
                value=value,
            )
            session.add(tag_entry)

    # Add sample associations (resolve sample_name → Sample.id via FK)
    if file_create.samples:
        for sample_input in file_create.samples:
            resolved_sample_id = resolve_or_create_sample(
                session=session,
                sample_name=sample_input.sample_name,
                project_id=project_id,
            )
            sample_assoc = FileSample(
                file_id=file_record.id,
                sample_id=resolved_sample_id,
                role=sample_input.role,
            )
            session.add(sample_assoc)

    return file_record


def _check_duplicate_record(
    session: Session,
    qcrecord_create: QCRecordCreate,
    resolved_run_id: uuid_module.UUID | None = None,
) -> QCRecord | None:
    """
    Check if an equivalent QC record already exists.

    Scoped by project_id (project-scoped) or sequencing_run_id
    (run-scoped). Returns the existing record if found, None otherwise.
    """
    # Build scope filter based on project vs run
    if qcrecord_create.project_id:
        stmt = select(QCRecord).where(
            QCRecord.project_id == qcrecord_create.project_id
        )
    elif resolved_run_id:
        stmt = select(QCRecord).where(
            QCRecord.sequencing_run_id == resolved_run_id
        )
    else:
        return None

    stmt = stmt.order_by(col(QCRecord.created_on).desc())
    existing_records = session.exec(stmt).all()

    if not existing_records:
        return None

    # Check the latest record — simplified duplicate detection
    latest = existing_records[0]

    # Get existing metadata
    existing_metadata = {
        m.key: m.value
        for m in session.exec(
            select(QCRecordMetadata).where(
                QCRecordMetadata.qcrecord_id == latest.id
            )
        ).all()
    }

    # Compare metadata
    new_metadata = qcrecord_create.metadata or {}
    if existing_metadata == {k: str(v) for k, v in new_metadata.items()}:
        return latest

    return None


def search_qcrecords(
    session: Session,
    filter_on: dict | None = None,
    page: int = 1,
    per_page: int = 100,
    latest: bool = True,
) -> QCRecordsPublic:
    """
    Search for QC records with filtering and pagination.

    Args:
        session: Database session
        filter_on: Dictionary of fields to filter by
        page: Page number (1-based)
        per_page: Results per page
        latest: If True, return only the newest record per scope
                (project_id for project-scoped, sequencing_run_id
                 for run-scoped)
    """
    filter_on = filter_on or {}

    # Build base query
    stmt = select(QCRecord)

    # Apply filters
    if "project_id" in filter_on:
        project_ids = filter_on["project_id"]
        if isinstance(project_ids, list):
            stmt = stmt.where(
                col(QCRecord.project_id).in_(project_ids)
            )
        else:
            stmt = stmt.where(QCRecord.project_id == project_ids)

    # Filter by sequencing_run_id string (resolve to UUID)
    if "sequencing_run_id" in filter_on:
        run_id_str = filter_on["sequencing_run_id"]
        run = get_sequencing_run(
            session=session, run_id=run_id_str
        )
        if run:
            # Check both record-level and metric-level
            sr_subq = (
                select(QCMetric.qcrecord_id)
                .where(QCMetric.sequencing_run_id == run.id)
            )
            stmt = stmt.where(
                (QCRecord.sequencing_run_id == run.id)
                | col(QCRecord.id).in_(sr_subq)
            )
        else:
            # No matching run → return empty results
            stmt = stmt.where(QCRecord.id == None)  # noqa: E711

    # Filter by workflow_run_id (provenance)
    if "workflow_run_id" in filter_on:
        wf_run_id = filter_on["workflow_run_id"]
        if isinstance(wf_run_id, str):
            wf_run_id = uuid_module.UUID(wf_run_id)
        stmt = stmt.where(QCRecord.workflow_run_id == wf_run_id)

    # Handle metadata filtering
    if "metadata" in filter_on and isinstance(
        filter_on["metadata"], dict
    ):
        for key, value in filter_on["metadata"].items():
            subq = select(QCRecordMetadata.qcrecord_id).where(
                QCRecordMetadata.key == key,
                QCRecordMetadata.value == str(value)
            )
            stmt = stmt.where(col(QCRecord.id).in_(subq))

    # Order by created_on descending
    stmt = stmt.order_by(col(QCRecord.created_on).desc())

    # Execute to get all matching records
    all_records = list(session.exec(stmt).all())

    # Apply "latest" filter — newest per scope
    # Project-scoped: group by project_id
    # Run-scoped: group by sequencing_run_id
    if latest:
        seen_scopes: set = set()
        filtered_records = []
        for record in all_records:
            if record.project_id:
                scope_key = ("project", record.project_id)
            elif record.sequencing_run_id:
                scope_key = (
                    "run", str(record.sequencing_run_id)
                )
            else:
                scope_key = ("id", str(record.id))
            if scope_key not in seen_scopes:
                filtered_records.append(record)
                seen_scopes.add(scope_key)
        all_records = filtered_records

    # Calculate pagination
    total = len(all_records)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_records = all_records[start_idx:end_idx]

    # Convert to public format
    data = [
        _qcrecord_to_public(session, record)
        for record in paginated_records
    ]

    return QCRecordsPublic(
        data=data,
        total=total,
        page=page,
        per_page=per_page,
    )


def get_qcrecord_by_id(session: Session, qcrecord_id: str) -> QCRecordPublic:
    """Get a single QC record by ID."""

    try:
        record_uuid = uuid_module.UUID(qcrecord_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format: {qcrecord_id}"
        ) from exc

    record = session.get(QCRecord, record_uuid)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"QC record not found: {qcrecord_id}"
        )

    return _qcrecord_to_public(session, record)


def delete_qcrecord(session: Session, qcrecord_id: str) -> dict:
    """Delete a QC record and all associated data."""
    try:
        record_uuid = uuid_module.UUID(qcrecord_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format: {qcrecord_id}"
        ) from exc

    record = session.get(QCRecord, record_uuid)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"QC record not found: {qcrecord_id}"
        )

    # Delete associated file records via FileQCRecord junction table
    file_qcrecords = session.exec(
        select(FileQCRecord).where(
            FileQCRecord.qcrecord_id == record_uuid
        )
    ).all()

    for fqr in file_qcrecords:
        # Get the file and delete it (cascades to hashes, tags, samples, junction rows)
        file_record = session.get(File, fqr.file_id)
        if file_record:
            session.delete(file_record)

    # Delete the QC record (cascades to metadata, metrics, etc.)
    session.delete(record)
    session.commit()

    logger.info("Deleted QC record %s", qcrecord_id)

    return {"status": "deleted", "id": qcrecord_id}


def _convert_value_to_type(
    value_string: str, value_numeric: float | None, value_type: str
) -> str | int | float:
    """Convert stored values back to their original type."""
    if value_type == "int" and value_numeric is not None:
        return int(value_numeric)
    elif value_type == "float" and value_numeric is not None:
        return value_numeric
    return value_string


def _resolve_run_id_string(
    session: Session,
    sequencing_run_uuid: uuid_module.UUID | None,
) -> str | None:
    """Resolve a sequencing_run_id UUID to its run_id string."""
    if not sequencing_run_uuid:
        return None
    run = session.get(SequencingRun, sequencing_run_uuid)
    return run.run_id if run else None


def _qcrecord_to_public(
    session: Session, record: QCRecord
) -> QCRecordPublic:
    """Convert a QCRecord database object to public format."""
    # Resolve run_id string for record-level and metric-level
    record_run_id_str = _resolve_run_id_string(
        session, record.sequencing_run_id
    )

    # Get metadata
    metadata_entries = session.exec(
        select(QCRecordMetadata).where(
            QCRecordMetadata.qcrecord_id == record.id
        )
    ).all()

    metadata = [
        MetadataKeyValue(key=m.key, value=m.value)
        for m in metadata_entries
    ]

    # Get metrics
    metric_entries = session.exec(
        select(QCMetric).where(QCMetric.qcrecord_id == record.id)
    ).all()

    metrics = []
    for metric in metric_entries:
        # Get metric values
        values = session.exec(
            select(QCMetricValue).where(
                QCMetricValue.qc_metric_id == metric.id
            )
        ).all()

        # Get metric samples
        metric_samples = session.exec(
            select(QCMetricSample).where(
                QCMetricSample.qc_metric_id == metric.id
            )
        ).all()

        metric_sample_publics = []
        for ms in metric_samples:
            sample = session.get(Sample, ms.sample_id)
            sample_name = (
                sample.sample_id if sample else str(ms.sample_id)
            )
            metric_sample_publics.append(
                MetricSamplePublic(
                    sample_name=sample_name, role=ms.role
                )
            )

        # Resolve metric-level run_id string (may differ from record)
        metric_run_id_str = _resolve_run_id_string(
            session, metric.sequencing_run_id
        )

        metrics.append(MetricPublic(
            name=metric.name,
            samples=metric_sample_publics,
            sequencing_run_id=metric_run_id_str,
            workflow_run_id=metric.workflow_run_id,
            values=[
                MetricValuePublic(
                    key=v.key,
                    value=_convert_value_to_type(
                        v.value_string,
                        v.value_numeric,
                        v.value_type,
                    )
                )
                for v in values
            ],
        ))

    # Get file records via FileQCRecord junction table
    file_qcrecords = session.exec(
        select(FileQCRecord).where(
            FileQCRecord.qcrecord_id == record.id
        )
    ).all()

    output_files = []
    for fqr in file_qcrecords:
        file_record = session.get(File, fqr.file_id)
        if not file_record:
            continue

        # Get hashes
        hashes = session.exec(
            select(FileHash).where(
                FileHash.file_id == file_record.id
            )
        ).all()

        # Get tags
        tags = session.exec(
            select(FileTag).where(
                FileTag.file_id == file_record.id
            )
        ).all()

        # Get samples
        samples = session.exec(
            select(FileSample).where(
                FileSample.file_id == file_record.id
            )
        ).all()

        output_files.append(FileSummary(
            id=file_record.id,
            uri=file_record.uri,
            filename=file_record.filename,
            size=file_record.size,
            created_on=file_record.created_on,
            hashes=[
                HashPublic(
                    algorithm=h.algorithm, value=h.value
                )
                for h in hashes
            ],
            tags=[
                TagPublic(key=t.key, value=t.value)
                for t in tags
            ],
            samples=[
                FileSamplePublic(
                    sample_name=(
                        session.get(
                            Sample, s.sample_id
                        ).sample_id
                        if session.get(Sample, s.sample_id)
                        else str(s.sample_id)
                    ),
                    role=s.role
                )
                for s in samples
            ],
        ))

    return QCRecordPublic(
        id=record.id,
        created_on=record.created_on,
        created_by=record.created_by,
        project_id=record.project_id,
        sequencing_run_id=record_run_id_str,
        workflow_run_id=record.workflow_run_id,
        metadata=metadata,
        metrics=metrics,
        output_files=output_files,
    )
