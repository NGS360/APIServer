'''
NGS360 REST API Server
'''
from logging.config import dictConfig

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
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default'
    }},
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

def create_app(config_class=DefaultConfig):
    ''' Application Factory '''
    app = Flask(__name__)

    app.config.from_object(config_class)
    app.logger.info('%s loading', app.config['APP_NAME'])

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
                
            auth_host, remaining = rest.split('@', 1)
            
            # Return masked URI
            return f"{protocol}://****:****@{remaining}"
        except Exception:
            # If any parsing error occurs, return the original URI
            return uri

    for key, value in app.config.items():
        # Case 1: Key contains sensitive words - mask completely
        if any(sensitive_word in key.upper() for sensitive_word in ['PASSWORD', 'SECRET', 'KEY', 'TOKEN', 'CREDENTIAL']):
            app.logger.info('%s: %s', key, '********')
            continue

        # Case 2: Database URI - mask username and password
        if isinstance(value, str) and ('DATABASE_URI' in key.upper() or 'DB_URI' in key.upper() or 'CONNECTION' in key.upper()):
            masked_value = mask_db_uri(value)
            app.logger.info('%s: %s', key, masked_value)
            continue
            
        # Case 3: Regular config value - log as is
        app.logger.info('%s: %s', key, value)

    # Initialize 3rd party extensions
    init_extensions(app)

    # Register blueprints
    register_blueprints(app)

    app.logger.info('%s loaded.', app.config['APP_NAME'])
    return app
