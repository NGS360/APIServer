'''
NGS360 REST API Server
'''
from logging.config import dictConfig

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from config import DefaultConfig
from apiserver.api import BLUEPRINT_API

db = SQLAlchemy()
migrate = Migrate()

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

def init_extensions(app):
    ''' Initialize Flask Extensions '''
    app.logger.debug("Initializing extensions")

    app.logger.debug("Initializing SQLAlchemy")
    db.init_app(app)
    app.logger.debug("Initializing Flask-Migrate")
    migrate.init_app(app, db)

    app.logger.debug("Initialized extensions")

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
    for key, value in app.config.items():
        app.logger.info('%s: %s', key, value)

    # Initialize 3rd party extensions
    init_extensions(app)

    # Register blueprints
    register_blueprints(app)

    app.logger.info('%s loaded.', app.config['APP_NAME'])
    return app
