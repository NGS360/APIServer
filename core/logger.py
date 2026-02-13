"""
Configure the logger
"""

import logging
from core.config import get_settings

logging.basicConfig(
    level=get_settings().LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
