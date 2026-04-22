import uuid
from datetime import datetime, timezone
from typing import List, Literal

from fastapi import HTTPException, status
from pydantic import PositiveInt
from sqlmodel import Session, select, func
from sqlalchemy.orm import selectinload
from opensearchpy import OpenSearch

from core.utils import define_search_body
from core.logger import logger

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
    stub = Sample(
        sample_id=sample_name,
        project_id=project_id,
        created_at=datetime.now(timezone.utc),
    )
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
    sample = Sample(
        sample_id=sample_in.sample_id,
        project_id=project_id,
        created_at=datetime.now(timezone.utc),
    )
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

        # Parse and create project attributes
        # linking to new project
        sample_attributes = [
            SampleAttribute(sample_id=sample.id, key=attr.key, value=attr.value)
            for attr in sample_in.attributes
        ]

        # Update database with attribute links
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
    page: PositiveInt,
    per_page: PositiveInt,
    sort_by: str,
    sort_order: Literal["asc", "desc"],
) -> SamplesPublic:
    """
    Get a paginated list of samples for a specific project.

    Args:
        session: Database session
        project_id: Project ID to filter samples by
        page: Page number (1-based)
        per_page: Number of items per page
        sort_by: Column name to sort by
        sort_order: Sort direction ('asc' or 'desc')

    Returns:
        SamplesPublic: Paginated list of samples for the project
    """
    # Get the total count of samples for the project
    total_count = session.exec(
        select(func.count()).select_from(Sample).where(Sample.project_id == project_id)
    ).one()

    # Compute total pages
    total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

    # Calculate offset for pagination
    offset = (page - 1) * per_page

    # Build the select statement
    statement = select(Sample).where(Sample.project_id == project_id)

    # Add sorting
    if hasattr(Sample, sort_by):
        sort_column = getattr(Sample, sort_by)
        if sort_order == "desc":
            sort_column = sort_column.desc()
        statement = statement.order_by(sort_column)

    # Add pagination
    statement = statement.offset(offset).limit(per_page)

    # Execute the query
    samples = session.exec(statement).all()

    # Map to public samples
    public_samples = [
        SamplePublic(
            sample_id=sample.sample_id,
            project_id=sample.project_id,
            attributes=sample.attributes,
            # [
            #    {"key": attr.key, "value": attr.value} for attr in (sample.attributes or [])
            # ] if sample.attributes else []
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
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def get_sample_by_sample_id(session: Session, sample_id: str) -> Sample:
    """
    Returns a single sample by its sample_id.
    Note: This is different from its internal "id".
    """
    return None


def reindex_samples(session: Session, client: OpenSearch):
    """
    Index all samples in database with OpenSearch using bulk indexing.
    """
    samples = session.exec(select(Sample)).all()
    search_docs = [SearchDocument(id=str(s.id), body=s) for s in samples]
    reset_index(client, "samples")
    add_objects_to_index(client, search_docs, "samples")


# ---------------------------------------------------------------------------
# Shared sample query builder (used by v1 and legacy endpoints)
# ---------------------------------------------------------------------------

# Top-level fields that map to Sample columns
FIELD_MAP = {
    "projectid": "project_id",
    "samplename": "sample_id",
}


def _build_sample_query(
    filters: dict,
    tags: dict | None = None,
):
    """
    Build a SQLAlchemy select statement from sample filter parameters.

    Args:
        filters: dict of top-level or attribute filters.
            - Keys in FIELD_MAP are mapped to Sample columns.
            - 'created_on' is handled as date prefix match.
            - 'tags' key (if present) is extracted and handled separately.
            - Other keys are treated as SampleAttribute key searches.
        tags: Explicit tags dict (from POST body's filter_on.tags).

    Returns:
        A select statement for Sample objects with attributes eager-loaded.
    """
    statement = select(Sample).options(selectinload(Sample.attributes))

    # Extract tags from filters if present
    if tags is None:
        tags = filters.pop("tags", None)
    else:
        filters.pop("tags", None)  # Remove if also present in filters

    # Handle top-level and attribute filters
    attr_filters = {}
    for key, value in filters.items():
        column_name = FIELD_MAP.get(key)
        if column_name:
            # Map to Sample column
            column = getattr(Sample, column_name)
            if isinstance(value, list):
                statement = statement.where(column.in_(value))
            else:
                statement = statement.where(column == value)
        elif key == "created_on":
            # Date prefix match on Sample.created_at
            # e.g., "2026-01-21" matches any timestamp on that date
            if isinstance(value, str) and Sample.created_at is not None:
                try:
                    date = datetime.strptime(value, "%Y-%m-%d").date()
                    statement = statement.where(
                        func.date(Sample.created_at) == date
                    )
                except ValueError:
                    pass  # Invalid date format, skip filter
        else:
            # Unknown key — treat as attribute filter
            attr_filters[key] = value

    # Handle attribute filters (from unknown keys)
    for attr_key, attr_value in attr_filters.items():
        # Case-insensitive key matching
        attr_subquery = (
            select(SampleAttribute.sample_id)
            .where(
                func.upper(SampleAttribute.key) == attr_key.upper(),
                SampleAttribute.value == attr_value,
            )
        )
        statement = statement.where(Sample.id.in_(attr_subquery))

    # Handle tags dict (from POST body)
    if tags and isinstance(tags, dict):
        for tag_key, tag_value in tags.items():
            attr_subquery = (
                select(SampleAttribute.sample_id)
                .where(
                    func.upper(SampleAttribute.key) == tag_key.upper(),
                    SampleAttribute.value == tag_value,
                )
            )
            statement = statement.where(Sample.id.in_(attr_subquery))

    return statement


# ---------------------------------------------------------------------------
# V1 structured sample search (SQL-backed)
# ---------------------------------------------------------------------------


def search_samples_v1(
    session: Session,
    filters: dict,
    tags: dict | None = None,
    page: int = 1,
    per_page: int = 20,
) -> SamplesPublic:
    """
    Search samples using structured filters, returning v1 response format.

    Args:
        session: Database session
        filters: dict of filter parameters (projectid, samplename,
                 created_on, attribute keys, tags)
        tags: Optional explicit tags dict
        page: Page number (1-indexed)
        per_page: Number of items per page

    Returns:
        SamplesPublic with paginated results and data_cols
    """
    # Build query for total count (without pagination)
    # We need separate copies because _build_sample_query mutates filters
    count_filters = dict(filters)
    count_tags = dict(tags) if tags else None
    count_stmt = _build_sample_query(count_filters, count_tags)
    all_results = session.exec(count_stmt).all()
    total_count = len(all_results)

    total_pages = (total_count + per_page - 1) // per_page if total_count else 0

    # Build query with pagination
    page_filters = dict(filters)
    page_tags = dict(tags) if tags else None
    statement = _build_sample_query(page_filters, page_tags)
    offset = (page - 1) * per_page
    statement = statement.offset(offset).limit(per_page)
    samples = session.exec(statement).all()

    # Map to SamplePublic
    public_samples = [
        SamplePublic(
            sample_id=sample.sample_id,
            project_id=sample.project_id,
            attributes=sample.attributes,
        )
        for sample in samples
    ]

    # Collect all unique attribute keys across matched samples for data_cols
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
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


# ---------------------------------------------------------------------------
# OpenSearch free-text sample search (for unified /api/v1/search)
# ---------------------------------------------------------------------------


def search_samples_opensearch(
    session: Session,
    client: OpenSearch,
    query: str,
    page: int = 1,
    per_page: int = 5,
    sort_by: str | None = "sample_id",
    sort_order: Literal["asc", "desc"] | None = "asc",
) -> SamplesPublic:
    """
    Search samples using OpenSearch free-text query.
    Used by the unified /api/v1/search endpoint.
    """
    search_body = define_search_body(
        query, page, per_page, sort_by, sort_order
    )

    try:
        response = client.search(index="samples", body=search_body)
        total_items = response["hits"]["total"]["value"]
        total_pages = (
            (total_items + per_page - 1) // per_page if total_items else 0
        )

        results = []
        for hit in response["hits"]["hits"]:
            # The _id is the sample UUID; look up full record from DB
            sample_uuid = hit["_id"]
            sample = session.exec(
                select(Sample)
                .options(selectinload(Sample.attributes))
                .where(Sample.id == sample_uuid)
            ).first()
            if sample:
                results.append(
                    SamplePublic(
                        sample_id=sample.sample_id,
                        project_id=sample.project_id,
                        attributes=sample.attributes,
                    )
                )

        return SamplesPublic(
            data=results,
            data_cols=None,
            total_items=total_items,
            total_pages=total_pages,
            current_page=page,
            per_page=per_page,
            has_next=page < total_pages,
            has_prev=page > 1,
        )
    except Exception as e:
        logger.error("OpenSearch sample search failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


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

    Each item may optionally include a ``run_barcode`` to associate
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

    # 2. Resolve all unique run barcodes up-front
    unique_barcodes = {
        item.run_barcode for item in samples_in if item.run_barcode
    }
    barcode_to_run: dict[str, SequencingRun] = {}
    invalid_barcodes: list[str] = []
    for barcode in unique_barcodes:
        try:
            run = get_run(session=session, run_barcode=barcode)
        except (ValueError, Exception):
            run = None
        if run is None:
            invalid_barcodes.append(barcode)
        else:
            barcode_to_run[barcode] = run

    if invalid_barcodes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Run barcode(s) not found: "
                f"{', '.join(sorted(invalid_barcodes))}"
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
    associations_created = 0
    associations_existing = 0
    total_files_created = 0
    total_files_skipped = 0
    items: list[BulkSampleItemResponse] = []
    newly_created_samples: list[Sample] = []

    for item in samples_in:
        created = False

        # Resolve or create the sample
        existing = session.exec(
            select(Sample).where(
                Sample.sample_id == item.sample_id,
                Sample.project_id == project.project_id,
            )
        ).first()

        if existing:
            sample = existing
            samples_existing += 1
        else:
            sample = Sample(
                sample_id=item.sample_id,
                project_id=project.project_id,
                created_at=datetime.now(timezone.utc),
            )
            session.add(sample)
            session.flush()  # get the UUID

            # Create attributes
            if item.attributes:
                attrs = [
                    SampleAttribute(
                        sample_id=sample.id, key=a.key, value=a.value
                    )
                    for a in item.attributes
                ]
                session.add_all(attrs)

            samples_created += 1
            created = True
            newly_created_samples.append(sample)

        # Associate with sequencing run if requested
        run_barcode_echo: str | None = None
        if item.run_barcode:
            run = barcode_to_run[item.run_barcode]
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

            run_barcode_echo = item.run_barcode

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
                run_barcode=run_barcode_echo,
                files_created=item_files_created,
                files_skipped=item_files_skipped,
            )
        )
        total_files_created += item_files_created
        total_files_skipped += item_files_skipped

    # Single commit — all or nothing
    session.commit()

    # ── Post-commit: index newly created samples in OpenSearch ────────
    if opensearch_client:
        for sample in newly_created_samples:
            session.refresh(sample)
            search_doc = SearchDocument(id=str(sample.id), body=sample)
            try:
                add_object_to_index(opensearch_client, search_doc, index="samples")
            except Exception:
                pass  # best-effort indexing

    return BulkSampleCreateResponse(
        project_id=project.project_id,
        samples_created=samples_created,
        samples_existing=samples_existing,
        associations_created=associations_created,
        associations_existing=associations_existing,
        files_created=total_files_created,
        files_skipped=total_files_skipped,
        items=items,
    )
