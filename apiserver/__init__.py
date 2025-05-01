'''
NGS360 REST API Server
'''
import logging
from logging.config import dictConfig
from logging.handlers import TimedRotatingFileHandler, SMTPHandler

from flask import Flask

from config import DefaultConfig
from apiserver.extensions import init_extensions

from apiserver.api import BLUEPRINT_API

# Configure (default) logging
dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {
        'wsgi': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://flask.logging.wsgi_errors_stream',
            'formatter': 'default'
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi']
    }
})


def register_blueprints(app):
    ''' Register blueprints '''
    app.logger.debug("Registering blueprints")

    app.logger.debug("Registering API blueprint")
    app.register_blueprint(BLUEPRINT_API)

    app.logger.debug("Registered blueprints")


def print_environment_variables(app):
    ''' Print environment variables to the log'''
    def mask_db_uri(uri):
        """Mask username and password in database URIs"""
        if not (isinstance(uri, str) and '://' in uri and '@' in uri):
            return uri

        try:
            # Split the URI into protocol and the rest
            protocol, rest = uri.split('://', 1)

            # Split the rest into auth+host and the remaining parts
            if '@' not in rest:
                return uri

            _, remaining = rest.split('@', 1)

            # Return masked URI
            return f"{protocol}://****:****@{remaining}"
        except Exception: # pylint: disable=broad-except
            # If any parsing error occurs, return the original URI
            return uri

    for key, value in app.config.items():
        # Case 1: Key contains sensitive words - mask completely
        if any(sensitive_word in key.upper() for sensitive_word in
               ['PASSWORD', 'SECRET', 'KEY', 'TOKEN', 'CREDENTIAL']):
            app.logger.info('%s: %s', key, '********')
            continue

        # Case 2: Database URI - mask username and password
        if isinstance(value, str) and ('DATABASE_URI' in
                key.upper() or 'DB_URI' in key.upper() or 'CONNECTION' in key.upper()):
            masked_value = mask_db_uri(value)
            app.logger.info('%s: %s', key, masked_value)
            continue

        # Case 3: Regular config value - log as is
        app.logger.info('%s: %s', key, value)

def setup_logging(app):
    ''' Setup logging '''
    if not app.debug:
        # If FLASK_LOG_FILE and FLASK_LOG_LEVEL env vars defined, set up logging.
        log_file = app.config.get('FLASK_LOG_FILE')
        log_level = app.config.get('FLASK_LOG_LEVEL')
        # log to a file if defined
        if log_file and log_level:
            app.logger.info("Setting up file logging to %s", log_file)
            file_handler = TimedRotatingFileHandler(log_file, when='midnight', backupCount=10)
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
            file_handler.setLevel(log_level)
            app.logger.addHandler(file_handler)

        # Send emails on critical errors
        mail_server = app.config.get('MAIL_SERVER')
        if mail_server:
            mail_username = app.config.get('MAIL_USERNAME')
            mail_password = app.config.get('MAIL_PASSWORD')
            auth = None
            app.logger.info("Setting up email logger")
            if mail_username and mail_password:
                auth = (mail_username, mail_password)

            secure = None
            if 'MAIL_USE_TLS' in app.config:
                secure = ()

            mail_handler = SMTPHandler(
                mailhost=(mail_server, app.config['MAIL_PORT']),
                fromaddr=f"no-reply@{mail_server}",
                toaddrs=app.config['MAIL_ADMINS'], subject=f"{app.config['APP_NAME']} Failure",
                credentials=auth, secure=secure)
            mail_handler.setLevel(logging.ERROR)
            app.logger.addHandler(mail_handler)

    app.logger.setLevel(logging.DEBUG)

def create_app(config_class=DefaultConfig):
    ''' Application Factory '''
    app = Flask(__name__)

    app.config.from_object(config_class)

    setup_logging(app)

    app.logger.info('%s loading', app.config['APP_NAME'])

    print_environment_variables(app)

    # Initialize 3rd party extensions
    init_extensions(app)

    # Register blueprints
    register_blueprints(app)

    app.logger.info('%s loaded.', app.config['APP_NAME'])
    return app
