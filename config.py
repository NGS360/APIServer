"""Application Config profiles"""

import os


class DefaultConfig: # pylint: disable=too-few-public-methods
    """Default Config profile"""

    APP_NAME = os.environ.get("APP_NAME", "NGS360")
    DEBUG = os.environ.get("FLASK_DEBUG", False)

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URI", "mysql+pymysql://user:password@localhost/flaskdb"
    )

    FLASK_LOG_FILE = os.environ.get("FLASK_LOG_FILE", None)
    FLASK_LOG_LEVEL = os.environ.get("FLASK_LOG_LEVEL", None)

    MAIL_SERVER = os.environ.get("MAIL_SERVER", None)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", None)
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", None)
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", False)
    MAIL_PORT = os.environ.get("MAIL_PORT", None)
    MAIL_ADMINS = os.environ.get("MAIL_ADMINS", None)

class TestConfig(DefaultConfig): # pylint: disable=too-few-public-methods
    """Unit Test Config profile"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
