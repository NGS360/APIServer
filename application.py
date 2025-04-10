''' NGS360 API Server '''
from flask import current_app
from dotenv import load_dotenv
from sqlalchemy.sql import text

from apiserver import create_app
from apiserver.extensions import DB
# this is needed to register the models for flask-migrate / Alembic migrations
from apiserver import models # pylint: disable=unused-import

load_dotenv()
app = create_app()

@app.route('/healthcheck')
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
    app.run(host='0.0.0.0')
