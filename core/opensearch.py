"""
OpenSearch configuration
"""

from opensearchpy import OpenSearch
from core.app_settings import app_settings
from core.logger import logger

INDEXES = ["projects", "samples", "illumina_runs"]

client = None


def get_opensearch_client():
    global client

    if client:
        return client

    # Connect to opensearch
    os_user = app_settings.get("OPENSEARCH_USER")
    os_password = app_settings.get("OPENSEARCH_PASSWORD")

    if os_user and os_password:
        auth = (os_user, os_password)
    else:
        auth = None

    os_host = app_settings.get("OPENSEARCH_HOST")

    if not os_host:
        client = None
    else:
        client = OpenSearch(
            hosts=[
                {
                    "host": os_host,
                    "port": app_settings.get("OPENSEARCH_PORT"),
                }
            ],
            http_compress=True,
            http_auth=auth,
            use_ssl=app_settings.get_bool(
                "OPENSEARCH_USE_SSL", default=True
            ),
            verify_certs=app_settings.get_bool(
                "OPENSEARCH_VERIFY_CERTS", default=False
            ),
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
