from sqlmodel import Session, select


from api.samples.models import (
    Sample
)
from api.search.models import (
    SearchDocument,
)
from opensearchpy import OpenSearch
from api.search.services import add_object_to_index, delete_index


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
