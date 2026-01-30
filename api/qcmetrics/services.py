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
    QCRecordPublic,
    QCRecordsPublic,
    MetadataKeyValue,
    MetricPublic,
    MetricValuePublic,
    MetricSamplePublic,
    MetricInput,
)
from api.filerecord.models import (
    FileRecord,
    FileRecordHash,
    FileRecordTag,
    FileRecordSample,
    FileRecordEntityType,
    FileRecordCreate,
    FileRecordPublic,
    HashPublic,
    TagPublic,
    SamplePublic,
)


logger = logging.getLogger(__name__)


def create_qcrecord(
    session: Session,
    qcrecord_create: QCRecordCreate,
    created_by: str,
) -> QCRecordPublic:
    """
    Create a new QC record with all associated data.

    Metrics can have numeric values (int, float) which are stored as strings
    in the database.
    """
    # Check for duplicate record
    existing = _check_duplicate_record(session, qcrecord_create)
    if existing:
        logger.info(
            "Equivalent QC record already exists for project %s: %s",
            qcrecord_create.project_id,
            existing.id
        )
        return _qcrecord_to_public(session, existing)

    # Create main QC record
    qcrecord = QCRecord(
        created_on=datetime.now(timezone.utc),
        created_by=created_by,
        project_id=qcrecord_create.project_id,
    )
    session.add(qcrecord)
    session.flush()  # Get the ID

    # Add metadata
    if qcrecord_create.metadata:
        for key, value in qcrecord_create.metadata.items():
            metadata_entry = QCRecordMetadata(
                qcrecord_id=qcrecord.id,
                key=key,
                value=str(value),
            )
            session.add(metadata_entry)

    # Add metrics
    if qcrecord_create.metrics:
        for metric_input in qcrecord_create.metrics:
            _create_metric(session, qcrecord.id, metric_input)

    # Add output files
    if qcrecord_create.output_files:
        for file_create in qcrecord_create.output_files:
            _create_file_record(
                session,
                entity_type=FileRecordEntityType.QCRECORD,
                entity_id=qcrecord.id,
                file_create=file_create,
            )

    session.commit()
    session.refresh(qcrecord)

    logger.info(
        "Created QC record %s for project %s by %s",
        qcrecord.id,
        qcrecord.project_id,
        created_by
    )

    return _qcrecord_to_public(session, qcrecord)


def _create_metric(
    session: Session,
    qcrecord_id,
    metric_input: MetricInput,
) -> QCMetric:
    """Create a metric group with its samples and values."""
    metric = QCMetric(
        qcrecord_id=qcrecord_id,
        name=metric_input.name,
    )
    session.add(metric)
    session.flush()

    # Add sample associations
    if metric_input.samples:
        for sample_input in metric_input.samples:
            sample_assoc = QCMetricSample(
                qc_metric_id=metric.id,
                sample_name=sample_input.sample_name if hasattr(sample_input, 'sample_name')
                else sample_input['sample_name'],
                role=sample_input.role if hasattr(sample_input, 'role')
                else sample_input.get('role'),
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


def _create_file_record(
    session: Session,
    entity_type: FileRecordEntityType,
    entity_id,
    file_create: FileRecordCreate,
) -> FileRecord:
    """Create a file record with its hashes, tags, and samples."""
    file_record = FileRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        uri=file_create.uri,
        size=file_create.size,
        created_on=file_create.created_on,
    )
    session.add(file_record)
    session.flush()

    # Add hashes
    if file_create.hash:
        for algorithm, value in file_create.hash.items():
            hash_entry = FileRecordHash(
                file_record_id=file_record.id,
                algorithm=algorithm,
                value=value,
            )
            session.add(hash_entry)

    # Add tags
    if file_create.tags:
        for key, value in file_create.tags.items():
            tag_entry = FileRecordTag(
                file_record_id=file_record.id,
                key=key,
                value=str(value),
            )
            session.add(tag_entry)

    # Add sample associations
    if file_create.samples:
        for sample_input in file_create.samples:
            sample_assoc = FileRecordSample(
                file_record_id=file_record.id,
                sample_name=sample_input.sample_name,
                role=sample_input.role,
            )
            session.add(sample_assoc)

    return file_record


def _check_duplicate_record(
    session: Session,
    qcrecord_create: QCRecordCreate,
) -> QCRecord | None:
    """
    Check if an equivalent QC record already exists.

    Returns the existing record if found, None otherwise.
    """
    # Find existing records for this project
    stmt = select(QCRecord).where(
        QCRecord.project_id == qcrecord_create.project_id
    ).order_by(col(QCRecord.created_on).desc())

    existing_records = session.exec(stmt).all()

    if not existing_records:
        return None

    # For now, just check the latest record
    # A full comparison would require comparing all nested data
    # This is a simplified version that checks metadata keys
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
        # Metadata matches - could do deeper comparison here
        # For now, consider it a duplicate if metadata matches
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
        latest: If True, return only the newest record per project
    """
    filter_on = filter_on or {}

    # Build base query
    stmt = select(QCRecord)

    # Apply filters
    if "project_id" in filter_on:
        project_ids = filter_on["project_id"]
        if isinstance(project_ids, list):
            stmt = stmt.where(col(QCRecord.project_id).in_(project_ids))
        else:
            stmt = stmt.where(QCRecord.project_id == project_ids)

    # Handle metadata filtering
    if "metadata" in filter_on and isinstance(filter_on["metadata"], dict):
        for key, value in filter_on["metadata"].items():
            # Subquery to find QCRecords with matching metadata
            subq = select(QCRecordMetadata.qcrecord_id).where(
                QCRecordMetadata.key == key,
                QCRecordMetadata.value == str(value)
            )
            stmt = stmt.where(col(QCRecord.id).in_(subq))

    # Order by created_on descending
    stmt = stmt.order_by(col(QCRecord.created_on).desc())

    # Execute to get all matching records
    all_records = list(session.exec(stmt).all())

    # Apply "latest" filter - keep only newest per project
    if latest:
        seen_projects = set()
        filtered_records = []
        for record in all_records:
            if record.project_id not in seen_projects:
                filtered_records.append(record)
                seen_projects.add(record.project_id)
        all_records = filtered_records

    # Calculate pagination
    total = len(all_records)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_records = all_records[start_idx:end_idx]

    # Convert to public format
    data = [_qcrecord_to_public(session, record) for record in paginated_records]

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

    # Delete associated file records (polymorphic, not cascade)
    file_records = session.exec(
        select(FileRecord).where(
            FileRecord.entity_type == FileRecordEntityType.QCRECORD,
            FileRecord.entity_id == record_uuid
        )
    ).all()

    for file_record in file_records:
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


def _qcrecord_to_public(session: Session, record: QCRecord) -> QCRecordPublic:
    """Convert a QCRecord database object to public format."""
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
            select(QCMetricValue).where(QCMetricValue.qc_metric_id == metric.id)
        ).all()

        # Get metric samples
        samples = session.exec(
            select(QCMetricSample).where(QCMetricSample.qc_metric_id == metric.id)
        ).all()

        metrics.append(MetricPublic(
            name=metric.name,
            samples=[
                MetricSamplePublic(sample_name=s.sample_name, role=s.role)
                for s in samples
            ],
            values=[
                MetricValuePublic(
                    key=v.key,
                    value=_convert_value_to_type(
                        v.value_string, v.value_numeric, v.value_type
                    )
                )
                for v in values
            ],
        ))

    # Get file records
    file_records = session.exec(
        select(FileRecord).where(
            FileRecord.entity_type == FileRecordEntityType.QCRECORD,
            FileRecord.entity_id == record.id
        )
    ).all()

    output_files = []
    for file_record in file_records:
        # Get hashes
        hashes = session.exec(
            select(FileRecordHash).where(
                FileRecordHash.file_record_id == file_record.id
            )
        ).all()

        # Get tags
        tags = session.exec(
            select(FileRecordTag).where(
                FileRecordTag.file_record_id == file_record.id
            )
        ).all()

        # Get samples
        samples = session.exec(
            select(FileRecordSample).where(
                FileRecordSample.file_record_id == file_record.id
            )
        ).all()

        output_files.append(FileRecordPublic(
            id=file_record.id,
            uri=file_record.uri,
            size=file_record.size,
            created_on=file_record.created_on,
            hashes=[HashPublic(algorithm=h.algorithm, value=h.value) for h in hashes],
            tags=[TagPublic(key=t.key, value=t.value) for t in tags],
            samples=[SamplePublic(sample_name=s.sample_name, role=s.role) for s in samples],
        ))

    return QCRecordPublic(
        id=record.id,
        created_on=record.created_on,
        created_by=record.created_by,
        project_id=record.project_id,
        metadata=metadata,
        metrics=metrics,
        output_files=output_files,
    )
