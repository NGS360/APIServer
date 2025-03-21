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
    from apiserver.api import BLUEPRINT_API
    app.logger.debug("Registering blueprints")

    app.logger.debug("Registering API blueprint")
    app.register_blueprint(BLUEPRINT_API)

    app.logger.debug("Registered blueprints")

def create_app(config_class=DefaultConfig):
    ''' Application Factory '''
    app = Flask(__name__)

    app.config.from_object(config_class)
    app.logger.info('%s loading', app.config['APP_NAME'])
    for key, value in app.config.items():
        app.logger.info('%s: %s', key, value)

    # Initialize 3rd party extensions
    init_extensions(app)

    # Register blueprints
    register_blueprints(app)

    app.logger.info('%s loaded.', app.config['APP_NAME'])
    return app
