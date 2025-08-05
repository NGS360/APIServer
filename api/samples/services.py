from typing import List, Literal
from pydantic import PositiveInt

from sqlmodel import Session

from api.samples.models import Sample, SampleCreate

def create_sample(session: Session, sample_in: SampleCreate) -> Sample:
    """
    Create a new sample with optional attributes.
    """
    return None

def get_samples(
      *, 
      session: Session, 
      page: PositiveInt, 
      per_page: PositiveInt, 
      sort_by: str,
      sort_order: Literal['asc', 'desc']
   ) -> List[Sample]:
    return None

def get_sample_by_sample_id(
    session: Session,
    sample_id: str) -> Sample:
    """
    Returns a single sample by its sample_id.
    Note: This is different from its internal "id".
    """
    return None
