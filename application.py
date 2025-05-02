''' NGS360 API Server '''
# pylint: disable=wrong-import-position
# Environment variables are loaded from .env file first,
# before DefaultConfig is loaded or else DefaultConfig will not see
# the environment variables set in .env file.
from dotenv import load_dotenv
load_dotenv()

from flask import current_app
from sqlalchemy.sql import text

from apiserver import create_app
from apiserver.extensions import DB
# this is needed to register the models for flask-migrate / Alembic migrations
from apiserver import models # pylint: disable=unused-import
# pylint: enable=wrong-import-position

application = create_app()

@application.route('/healthcheck')
def healthcheck():
    ''' Healthcheck endpoint '''
    try:
        current_app.logger.debug('Checking database connection')
        DB.session.query(text('1')).from_statement(text('SELECT 1')).all()
        current_app.logger.debug('Checking database connection...OK')
        return '<h1>It works.</h1>'
    except Exception as e: # pylint: disable=broad-exception-caught
        # e holds description of the error
        current_app.logger.debug('Checking database connection...FAILED')
        current_app.logger.error('Error: %s', e)
        error_text = "<p>The error:<br>" + str(e) + "</p>"
        hed = '<h1>Something is broken.</h1>'
        return hed + error_text

if __name__ == '__main__':
    # host should be 0.0.0.0 when running in a Docker container
    #application.run(host='0.0.0.0')
    # but not when run in ElasticBeanStalk
    application.run()
