'''
Projects API
'''
from flask import request, current_app
from flask_restx import Namespace, Resource

from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from apiserver.models import Project, ProjectAttribute
from apiserver.extensions import DB as db

NS = Namespace('projects', description='Projects API')

@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects '''
        projects = db.session.query(Project).options(joinedload(Project.attributes)).all()
        return [project.to_dict() for project in projects]

    def post(self):
        ''' POST /projects '''
        data = request.get_json()

        # Extract attributes from request data if provided
        attributes_data = data.pop('attributes', {})

        # Create project instance
        project = Project(**data)

        # Add attributes if provided
        for key, value in attributes_data.items():
            project.attributes.append(ProjectAttribute(key=key, value=value))

        # Save to database
        try:
            db.session.add(project)
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            current_app.logger.error('Error creating project, %s:', project)
            current_app.logger.error('Error is: %s', error)
            return {'message': 'Error creating project.'}, 400

        return project.to_dict(), 201
