"""
Routes/endpoints for the Samples API
"""

import uuid

# from typing import Literal
from fastapi import APIRouter, status  # Query
from core.deps import SessionDep, OpenSearchDep
from api.auth.deps import CurrentSuperuser
# from api.samples.models import Sample, SampleCreate, SamplePublic, SamplesPublic
import api.samples.services as services

router = APIRouter(prefix="/samples", tags=["Sample Endpoints"])

# @router.get(
#  "/{sample_id}",
#  response_model=SamplePublic,
#  tags=["Sample Endpoints"]
# )
# def get_sample_by_sample_id(session: SessionDep, sample_id: str) -> Sample:
#  """
#  Returns a single sample by its sample_id.
#  Note: This is different from its internal "id".
#  """
#  return services.get_sample_by_sample_id(
#    session=session,
#    sample_id=sample_id
#  )


@router.post(
    "/search",
    status_code=status.HTTP_201_CREATED,
    tags=["Sample Endpoints"],
)
def reindex_samples(
    session: SessionDep,
    client: OpenSearchDep,
):
    """
    Reindex samples in database with OpenSearch
    """
    services.reindex_samples(session, client)
    return 'OK'


@router.delete(
    "/{sample_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a sample (admin only)",
)
def delete_sample(
    sample_id: uuid.UUID,
    session: SessionDep,
    opensearch_client: OpenSearchDep,
    current_user: CurrentSuperuser,
) -> None:
    """
    Permanently delete a sample by UUID.

    Removes the sample and all associated data (attributes,
    run associations, file–sample links).  Requires superuser
    privileges.
    """
    services.delete_sample(session, opensearch_client, sample_id)
