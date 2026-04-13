import logging
import uuid
from typing import List, Literal

from fastapi import HTTPException, status
from pydantic import PositiveInt
from sqlmodel import Session, select, func
from opensearchpy import OpenSearch

from api.samples.models import (
    Sample,
    SampleCreate,
    SamplePublic,
    SamplesPublic,
    SampleAttribute,
    BulkSampleCreateResponse,
    BulkSampleItemResponse,
)
from api.project.models import Project
from api.runs.models import SequencingRun, SampleSequencingRun
from api.search.models import SearchDocument
from api.search.services import add_object_to_index, delete_index, delete_document_from_index

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
    Index all samples in database with OpenSearch
    """
    delete_index(client, "samples")
    samples = session.exec(
        select(Sample)
    ).all()
    for sample in samples:
        search_doc = SearchDocument(id=str(sample.id), body=sample)
        add_object_to_index(client, search_doc, index="samples")


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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

        items.append(
            BulkSampleItemResponse(
                sample_id=item.sample_id,
                sample_uuid=sample.id,
                project_id=project.project_id,
                created=created,
                run_barcode=run_barcode_echo,
            )
        )

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
        items=items,
    )


# ---------------------------------------------------------------------------
# Delete sample
# ---------------------------------------------------------------------------


def delete_sample(
    session: Session,
    opensearch_client: OpenSearch | None,
    sample_uuid: uuid.UUID,
) -> None:
    """
    Permanently delete a sample and all its associated data.

    Deletes the sample record along with:
    - SampleAttribute rows (via cascade)
    - FileSample junction rows (via cascade from Sample side)
    - SampleSequencingRun association rows

    Also removes the sample from the OpenSearch index.

    Args:
        session: Database session
        opensearch_client: OpenSearch client (may be None)
        sample_uuid: UUID of the sample to delete

    Raises:
        HTTPException 404: If sample not found
    """
    sample = session.get(Sample, sample_uuid)
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample not found: {sample_uuid}",
        )

    # Delete SampleSequencingRun associations
    associations = session.exec(
        select(SampleSequencingRun).where(
            SampleSequencingRun.sample_id == sample_uuid
        )
    ).all()
    for assoc in associations:
        session.delete(assoc)

    # Delete FileSample associations (file ↔ sample links)
    from api.files.models import FileSample as FileSampleModel
    file_sample_links = session.exec(
        select(FileSampleModel).where(FileSampleModel.sample_id == sample_uuid)
    ).all()
    for link in file_sample_links:
        session.delete(link)

    # Delete attributes
    if sample.attributes:
        for attr in sample.attributes:
            session.delete(attr)

    # Delete the sample itself
    session.delete(sample)
    session.commit()

    # Remove from OpenSearch index (best-effort)
    if opensearch_client:
        try:
            delete_document_from_index(
                opensearch_client, str(sample_uuid), "samples"
            )
        except Exception:
            logger.warning(
                "Failed to remove sample %s from OpenSearch index", sample_uuid
            )
