from typing import List, Literal
from pydantic import PositiveInt

from sqlmodel import Session, select

from api.samples.models import Sample, SampleCreate

def create_sample(session: Session, sample_in: SampleCreate) -> Sample:
    """
    Create a new sample with optional attributes.
    """
    return None

def get_samples(
      *, 
      session: Session,
      project_id: str,
      page: PositiveInt, 
      per_page: PositiveInt, 
      sort_by: str,
      sort_order: Literal['asc', 'desc']
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
   # Calculate offset for pagination
    offset = (page - 1) * per_page

    # Build the select statement
    statement = select(Sample).where(Sample.project_id == project_id)
    
    # Add sorting
    if hasattr(Sample, sort_by):
        sort_column = getattr(Sample, sort_by)
        if sort_order == 'desc':
            sort_column = sort_column.desc()
        statement = statement.order_by(sort_column)
    
    # Add pagination
    statement = statement.offset(offset).limit(per_page)
    
    # Execute the query
    return session.exec(statement).all()


def get_sample_by_sample_id(
    session: Session,
    sample_id: str) -> Sample:
    """
    Returns a single sample by its sample_id.
    Note: This is different from its internal "id".
    """
    return None
