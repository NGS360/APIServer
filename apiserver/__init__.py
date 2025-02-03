'''
NGS360 REST API Server
'''
from flask import Flask

from config import DefaultConfig

def init_extensions(app):
    ''' Initialize Flask Extensions '''
    app.logger.debug("Initializing extensions")
    app.logger.debug("Initialized extensions")

def register_blueprints(app):
    ''' Register blueprints '''
    app.logger.debug("Registering blueprints")
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
