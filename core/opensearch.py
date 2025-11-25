"""
OpenSearch configuration
"""

from opensearchpy import OpenSearch
from core.config import get_settings
from core.logger import logger

INDEXES = ["projects", "samples", "illumina_runs"]

client = None


def get_opensearch_client():
    global client

    if client:
        return client

    # Connect to opensearch
    if get_settings().OPENSEARCH_USER and get_settings().OPENSEARCH_PASSWORD:
        auth = (get_settings().OPENSEARCH_USER, get_settings().OPENSEARCH_PASSWORD)
    else:
        auth = None

    if get_settings().OPENSEARCH_HOST is None:
        client = None
    else:
        client = OpenSearch(
            hosts=[
                {
                    "host": get_settings().OPENSEARCH_HOST,
                    "port": get_settings().OPENSEARCH_PORT,
                }
            ],
            http_compress=True,  # enables gzip compression for request bodies
            http_auth=auth,
            use_ssl=True,
            # verify_certs = True,
            # ssl_assert_hostname = False,
            # ssl_show_warn = False,
            # ca_certs = ca_certs_path
        )
    return client


def init_indexes(client):
    if client is None:
        return

    # Create index if it does not exist
    for index in INDEXES:
        if not client.indices.exists(index=index):
            client.indices.create(index=index)
            logger.info("Index '%s' created successfully.", index)
        else:
            logger.info("Index '%s' already exists.", index)
