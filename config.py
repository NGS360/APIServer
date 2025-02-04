"""Application Config profiles"""

import os


class DefaultConfig:  # pylint: disable=too-few-public-methods
    """Default Config profile"""

    APP_NAME = os.environ.get("APP_NAME", "NGS360")
    DEBUG = True

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URI", "mysql+pymysql://username:password@localhost/ngs360"
    )
