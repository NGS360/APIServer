import logging
import uuid
from typing import List, Literal

from fastapi import HTTPException, status
from sqlmodel import Session, select, func
from opensearchpy import OpenSearch

from api.samples.models import (
    Sample,
    SampleCreate,
    SampleFileInput,
    SamplePublic,
    SamplesPublic,
    SampleAttribute,
    BulkSampleCreateResponse,
    BulkSampleItemResponse,
)
from api.files.models import File, FileHash, FileTag, FileSample, FileProject
from api.project.models import Project
from api.runs.models import SequencingRun, SampleSequencingRun
from api.search.models import SearchDocument
from api.search.services import (
    add_object_to_index,
    add_objects_to_index,
    reset_index,
)

logger = logging.getLogger(__name__)


def resolve_or_create_sample(
    session: Session,
    sample_name: str,
    project_id: str,
) -> uuid.UUID:
    """
    Resolve a sample name to its UUID, creating a stub if it doesn't exist.

    Used by file and QCMetrics services when associating files/metrics with samples.
    If the sample doesn't exist, creates a stub Sample record tagged with
    SampleAttribute(key="auto_created_stub", value="true").

    Note: Does NOT commit the session — the caller manages the transaction.
    Note: Does NOT index to OpenSearch — stubs can be indexed during reconciliation.

    Args:
        session: Database session (caller manages commit)
        sample_name: Human-readable sample identifier (maps to Sample.sample_id)
        project_id: Project the sample belongs to

    Returns:
        UUID of the existing or newly created Sample record
    """
    existing = session.exec(
        select(Sample).where(
            Sample.sample_id == sample_name,
            Sample.project_id == project_id,
        )
    ).first()

    if existing:
        return existing.id

    # Create stub sample
    stub = Sample(sample_id=sample_name, project_id=project_id)
    session.add(stub)
    session.flush()  # Get the UUID

    # Tag as auto-created stub
    tag = SampleAttribute(
        sample_id=stub.id,
        key="auto_created_stub",
        value="true",
    )
    session.add(tag)

    return stub.id


def add_sample_to_project(
    session: Session,
    opensearch_client: OpenSearch,
    project_id: str,
    sample_in: SampleCreate,
) -> Sample:
    """
    Create a new sample with optional attributes.
    """
    # Check if project exists
    project = session.exec(
        select(Project).where(Project.project_id == project_id)
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    # Create initial sample
    sample = Sample(sample_id=sample_in.sample_id, project_id=project_id)
    session.add(sample)
    session.flush()

    # Handle attribute mapping
    if sample_in.attributes:
        # Prevent duplicate keys
        seen = set()
        keys = [attr.key for attr in sample_in.attributes]
        dups = [k for k in keys if k in seen or seen.add(k)]
        if dups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate keys ({', '.join(dups)}) are not allowed in project attributes.",
            )

        # Parse and create project attributes (skip empty/whitespace-only values)
        sample_attributes = [
            SampleAttribute(sample_id=sample.id, key=attr.key, value=attr.value)
            for attr in sample_in.attributes
            if attr.value is not None and attr.value.strip() != ""
        ]

        # Update database with attribute links
        if sample_attributes:
            session.add_all(sample_attributes)

    # With orm_mode=True, attributes will be eagerly loaded
    # and mapped to SamplePublic via response model
    session.commit()
    session.refresh(sample)

    # Add sample to opensearch
    if opensearch_client:
        search_doc = SearchDocument(id=str(sample.id), body=sample)
        add_object_to_index(opensearch_client, search_doc, index="samples")

    return sample


def get_samples(
    *,
    session: Session,
    project_id: str,
    skip: int = 0,
    limit: int = 100,
    sort_by: str,
    sort_order: Literal["asc", "desc"],
) -> SamplesPublic:
    """
    Get a paginated list of samples for a specific project.

    Args:
        session: Database session
        project_id: Project ID to filter samples by
        skip: Number of records to skip (offset)
        limit: Maximum number of records to return
        sort_by: Column name to sort by
        sort_order: Sort direction ('asc' or 'desc')

    Returns:
        SamplesPublic: Paginated list of samples for the project
    """
    # Get the total count of samples for the project
    total_count = session.exec(
        select(func.count()).select_from(Sample).where(Sample.project_id == project_id)
    ).one()

    # Build the select statement
    statement = select(Sample).where(Sample.project_id == project_id)

    # Add sorting
    if hasattr(Sample, sort_by):
        sort_column = getattr(Sample, sort_by)
        if sort_order == "desc":
            sort_column = sort_column.desc()
        statement = statement.order_by(sort_column)

    # Add pagination
    statement = statement.offset(skip).limit(limit)

    # Execute the query
    samples = session.exec(statement).all()

    # Map to public samples
    public_samples = [
        SamplePublic(
            sample_id=sample.sample_id,
            project_id=sample.project_id,
            attributes=sample.attributes,
        )
        for sample in samples
    ]

    # Collect all unique attribute keys across all samples for data_cols
    data_cols = None
    if samples:
        all_keys = set()
        for sample in samples:
            if sample.attributes:
                for attr in sample.attributes:
                    all_keys.add(attr.key)
        data_cols = sorted(list(all_keys)) if all_keys else None

    return SamplesPublic(
        data=public_samples,
        data_cols=data_cols,
        total_items=total_count,
        skip=skip,
        limit=limit,
        has_next=(skip + limit) < total_count,
        has_prev=skip > 0,
    )


def get_sample_by_sample_id(session: Session, sample_id: str) -> Sample:
    """
    Returns a single sample by its sample_id.
    Note: This is different from its internal "id".
    """
    return None


def reindex_samples(
    session: Session, client: OpenSearch, batch_size: int = 5000
):
    """
    Index all samples in database with OpenSearch.

    Processes samples in batches to bound memory usage for large datasets.
    """
    total = session.exec(
        select(func.count()).select_from(Sample)
    ).one()
    total_batches = (total + batch_size - 1) // batch_size if total else 0

    logger.info("Reindexing %d samples in %d batch(es) of %d", total, total_batches, batch_size)
    reset_index(client, "samples")

    indexed = 0
    batch_num = 0
    while True:
        samples = session.exec(
            select(Sample).offset(indexed).limit(batch_size)
        ).all()

        if not samples:
            break

        batch_num += 1
        search_docs = [
            SearchDocument(id=str(s.id), body=s) for s in samples
        ]
        add_objects_to_index(client, search_docs, "samples")

        indexed += len(samples)
        logger.info(
            "Indexing batch %d/%d — %d samples indexed out of %d total",
            batch_num, total_batches, indexed, total,
        )

        if len(samples) < batch_size:
            break

    logger.info("Reindex complete: %d samples indexed", indexed)


# ---------------------------------------------------------------------------
# Sample deletion
# ---------------------------------------------------------------------------


def delete_sample(
    session: Session,
    project_id: str,
    sample_id: str,
) -> None:
    """
    Hard-delete a sample and all its child rows.

    Explicitly deletes:
    - SampleAttribute rows (sample metadata)
    - FileSample rows (file associations — the File records themselves are NOT deleted)
    - SampleSequencingRun rows (run associations)

    Then deletes the Sample record itself.

    Args:
        session: Database session
        project_id: Project business key (string)
        sample_id: Sample identifier (Sample.sample_id, not the UUID)

    Raises:
        HTTPException 404: If sample not found in the given project
    """
    sample = session.exec(
        select(Sample).where(
            Sample.sample_id == sample_id,
            Sample.project_id == project_id,
        )
    ).first()

    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample '{sample_id}' not found in project '{project_id}'",
        )

    # Delete child rows explicitly (no cascade configured on Sample)
    # 1. SampleAttribute
    attrs = session.exec(
        select(SampleAttribute).where(SampleAttribute.sample_id == sample.id)
    ).all()
    for attr in attrs:
        session.delete(attr)

    # 2. FileSample (junction to files — files themselves are preserved)
    file_samples = session.exec(
        select(FileSample).where(FileSample.sample_id == sample.id)
    ).all()
    for fs in file_samples:
        session.delete(fs)

    # 3. SampleSequencingRun (junction to runs)
    run_assocs = session.exec(
        select(SampleSequencingRun).where(
            SampleSequencingRun.sample_id == sample.id
        )
    ).all()
    for ra in run_assocs:
        session.delete(ra)

    # Delete the sample itself
    session.delete(sample)
    session.commit()

    logger.info(
        "Deleted sample '%s' (UUID %s) from project '%s'",
        sample_id, sample.id, project_id,
    )


# ---------------------------------------------------------------------------
# Sample file creation helper (hash-aware dedup)
# ---------------------------------------------------------------------------


def _create_sample_files(
    session: Session,
    sample: Sample,
    project_uuid: uuid.UUID,
    file_inputs: List[SampleFileInput],
) -> tuple[int, int]:
    """
    Create File records and associate them with a sample, with hash-aware dedup.

    For each SampleFileInput:
    1. Check for an existing File linked to this sample via FileSample
       with the same URI.
    2. If found and input has no hashes → skip (assume identical).
    3. If found and input has hashes → compare against existing FileHash
       records. If all match → skip. If any differ → create new version.
    4. If no existing file → create new File + associations.

    Note: Does NOT commit — the caller manages the transaction.

    Args:
        session: Database session (caller manages commit)
        sample: The Sample ORM object (must have .id set via flush)
        project_uuid: The project's internal UUID for FileProject
        file_inputs: List of SampleFileInput to process

    Returns:
        Tuple of (files_created, files_skipped)
    """
    files_created = 0
    files_skipped = 0

    for fi in file_inputs:
        # Check for existing file linked to this sample with same URI
        existing_file = session.exec(
            select(File)
            .join(FileSample, FileSample.file_id == File.id)
            .where(
                FileSample.sample_id == sample.id,
                File.uri == fi.uri,
            )
        ).first()

        if existing_file is not None:
            if not fi.hashes:
                # No hashes provided — assume identical, skip
                files_skipped += 1
                continue

            # Compare provided hashes against existing FileHash records
            existing_hashes = {
                h.algorithm: h.value
                for h in session.exec(
                    select(FileHash).where(FileHash.file_id == existing_file.id)
                ).all()
            }

            all_match = all(
                existing_hashes.get(algo) == value
                for algo, value in fi.hashes.items()
            )

            if all_match:
                files_skipped += 1
                continue
            # Hashes differ — fall through to create a new version

        # ── Create new File record ────────────────────────────────────
        file_record = File(
            uri=fi.uri,
            original_filename=fi.original_filename,
            size=fi.size,
            source=fi.source,
            storage_backend=fi.storage_backend,
        )
        session.add(file_record)
        session.flush()  # get the file UUID

        # FileProject association
        session.add(FileProject(
            file_id=file_record.id,
            project_id=project_uuid,
        ))

        # FileSample association
        session.add(FileSample(
            file_id=file_record.id,
            sample_id=sample.id,
            role=fi.role,
        ))

        # FileHash records
        if fi.hashes:
            for algorithm, value in fi.hashes.items():
                session.add(FileHash(
                    file_id=file_record.id,
                    algorithm=algorithm,
                    value=value,
                ))

        # FileTag records
        if fi.tags:
            for key, value in fi.tags.items():
                session.add(FileTag(
                    file_id=file_record.id,
                    key=key,
                    value=value,
                ))

        files_created += 1

    return files_created, files_skipped


# ---------------------------------------------------------------------------
# Bulk sample creation
# ---------------------------------------------------------------------------


def bulk_create_samples(
    session: Session,
    opensearch_client: OpenSearch,
    project: Project,
    samples_in: List[SampleCreate],
    created_by: str,
) -> BulkSampleCreateResponse:
    """
    Create multiple samples in a single atomic transaction.

    Each item may optionally include a ``run_id`` to associate
    the sample with a sequencing run at creation time.

    All database writes happen in one transaction — if anything fails
    the entire batch is rolled back.

    Args:
        session: Database session
        opensearch_client: OpenSearch client for indexing
        project: The project object (already validated by route dependency)
        samples_in: List of SampleCreate items
        created_by: Username recorded on any SampleSequencingRun rows

    Returns:
        BulkSampleCreateResponse with per-item details and aggregate counts
    """
    from api.runs.services import get_run

    # ── Pre-validation ────────────────────────────────────────────────

    # 1. Check for duplicate sample_ids within the request
    seen_ids: set[str] = set()
    duplicates: list[str] = []
    for item in samples_in:
        if item.sample_id in seen_ids:
            duplicates.append(item.sample_id)
        seen_ids.add(item.sample_id)
    if duplicates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Duplicate sample_id(s) in request: "
                f"{', '.join(sorted(set(duplicates)))}"
            ),
        )

    # 2. Resolve all unique run IDs up-front
    unique_run_ids = {
        item.run_id for item in samples_in if item.run_id
    }
    run_id_to_run: dict[str, SequencingRun] = {}
    invalid_run_ids: list[str] = []
    for rid in unique_run_ids:
        try:
            run = get_run(session=session, run_id=rid)
        except (ValueError, Exception):
            run = None
        if run is None:
            invalid_run_ids.append(rid)
        else:
            run_id_to_run[rid] = run

    if invalid_run_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Run ID(s) not found: "
                f"{', '.join(sorted(invalid_run_ids))}"
            ),
        )

    # 3. Validate no duplicate attribute keys per sample
    for item in samples_in:
        if item.attributes:
            seen_keys: set[str] = set()
            dup_keys: list[str] = []
            for attr in item.attributes:
                if attr.key in seen_keys:
                    dup_keys.append(attr.key)
                seen_keys.add(attr.key)
            if dup_keys:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Duplicate attribute keys ({', '.join(dup_keys)}) "
                        f"on sample '{item.sample_id}'."
                    ),
                )

    # ── Transactional creation ────────────────────────────────────────

    samples_created = 0
    samples_existing = 0
    samples_updated = 0
    associations_created = 0
    associations_existing = 0
    total_files_created = 0
    total_files_skipped = 0
    items: list[BulkSampleItemResponse] = []
    newly_created_samples: list[Sample] = []
    updated_samples: list[Sample] = []

    for item in samples_in:
        created = False
        updated = False

        # Resolve or create the sample
        existing = session.exec(
            select(Sample).where(
                Sample.sample_id == item.sample_id,
                Sample.project_id == project.project_id,
            )
        ).first()

        if existing:
            sample = existing

            # ── Merge/upsert attributes on existing sample ────────
            if item.attributes:
                # Build a map of existing attributes for this sample
                existing_attrs = session.exec(
                    select(SampleAttribute).where(
                        SampleAttribute.sample_id == sample.id
                    )
                ).all()
                existing_attr_map = {a.key: a for a in existing_attrs}

                for attr in item.attributes:
                    is_empty = attr.value is None or attr.value.strip() == ""
                    ea = existing_attr_map.get(attr.key)

                    if is_empty:
                        # Column present but value blank → delete
                        if ea:
                            session.delete(ea)
                            updated = True
                    elif ea:
                        if ea.value != attr.value:
                            ea.value = attr.value
                            updated = True
                    else:
                        session.add(
                            SampleAttribute(
                                sample_id=sample.id,
                                key=attr.key,
                                value=attr.value,
                            )
                        )
                        updated = True

                # Remove auto_created_stub tag if real attributes arrive
                stub_attr = existing_attr_map.get("auto_created_stub")
                if stub_attr is not None:
                    session.delete(stub_attr)
                    updated = True

            if updated:
                samples_updated += 1
                updated_samples.append(sample)
            else:
                samples_existing += 1
        else:
            sample = Sample(
                sample_id=item.sample_id,
                project_id=project.project_id,
            )
            session.add(sample)
            session.flush()  # get the UUID

            # Create attributes (skip empty/whitespace-only values)
            if item.attributes:
                attrs = [
                    SampleAttribute(
                        sample_id=sample.id, key=a.key, value=a.value
                    )
                    for a in item.attributes
                    if a.value is not None and a.value.strip() != ""
                ]
                if attrs:
                    session.add_all(attrs)

            samples_created += 1
            created = True
            newly_created_samples.append(sample)

        # Associate with sequencing run if requested
        if item.run_id:
            run = run_id_to_run[item.run_id]
            existing_assoc = session.exec(
                select(SampleSequencingRun).where(
                    SampleSequencingRun.sample_id == sample.id,
                    SampleSequencingRun.sequencing_run_id == run.id,
                )
            ).first()

            if existing_assoc:
                associations_existing += 1
            else:
                assoc = SampleSequencingRun(
                    sample_id=sample.id,
                    sequencing_run_id=run.id,
                    created_by=created_by,
                )
                session.add(assoc)
                associations_created += 1

        # Create associated files if provided
        item_files_created = 0
        item_files_skipped = 0
        if item.files:
            item_files_created, item_files_skipped = _create_sample_files(
                session=session,
                sample=sample,
                project_uuid=project.id,
                file_inputs=item.files,
            )

        items.append(
            BulkSampleItemResponse(
                sample_id=item.sample_id,
                sample_uuid=sample.id,
                project_id=project.project_id,
                created=created,
                updated=updated,
                run_id=item.run_id,
                files_created=item_files_created,
                files_skipped=item_files_skipped,
            )
        )
        total_files_created += item_files_created
        total_files_skipped += item_files_skipped

    # Single commit — all or nothing
    session.commit()

    # ── Post-commit: index newly created and updated samples in OpenSearch ────────
    if opensearch_client and (newly_created_samples or updated_samples):
        search_docs = []
        for sample in newly_created_samples + updated_samples:
            session.refresh(sample)
            search_docs.append(SearchDocument(id=str(sample.id), body=sample))
        try:
            add_objects_to_index(opensearch_client, search_docs, index="samples")
        except Exception:
            pass  # best-effort indexing

    return BulkSampleCreateResponse(
        project_id=project.project_id,
        samples_created=samples_created,
        samples_existing=samples_existing,
        samples_updated=samples_updated,
        associations_created=associations_created,
        associations_existing=associations_existing,
        files_created=total_files_created,
        files_skipped=total_files_skipped,
        items=items,
    )
