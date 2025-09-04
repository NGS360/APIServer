from fastapi import HTTPException, status
from typing import List, Literal
from pydantic import PositiveInt

from sqlmodel import Session, select, func

from core.logger import logger

from api.samples.models import (
    Sample,
    SampleAttribute,
    SampleCreate,
    SamplePublic,
    SamplesPublic,
)
from api.project.models import Project
from api.search.models import (
    SearchDocument,
)
from opensearchpy import OpenSearch
from api.search.services import add_object_to_index


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
) -> List[Sample]:
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
        List of Sample objects
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
    return SamplesPublic(
        data=public_samples,
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
