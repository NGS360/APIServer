'''
Projects API
'''
from flask import request, current_app
from flask_restx import Namespace, Resource

from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from apiserver.models import Project as ProjectModel, ProjectAttribute, Sample
from apiserver.extensions import DB as db

NS = Namespace('projects', description='Projects API')

@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects '''
        projects = db.session.query(ProjectModel).options(joinedload(ProjectModel.attributes)).all()
        return [project.to_dict() for project in projects]

    def post(self):
        ''' POST /projects '''
        data = request.get_json()

        # Extract attributes from request data if provided
        attributes_data = data.pop('attributes', {})

        # Create project instance
        project = ProjectModel(**data)
        project.project_id = ProjectModel.generate_project_id()

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

@NS.route('/<string:project_id>')
class Project(Resource):
    ''' Projects API '''
    def get(self, project_id):
        ''' GET /projects/<project_id> '''
        project = db.session.query(ProjectModel).options(
            joinedload(ProjectModel.attributes)
        ).filter(ProjectModel.project_id == project_id).first()
        if project:
            return project.to_dict()
        return {'message': 'Project not found.'}, 404

@NS.route('/<string:project_id>/samples')
class ProjectSamples(Resource):
    ''' Project Samples API '''
    def get(self, project_id):
        ''' GET /projects/<project_id>/samples '''
        # This is Project().get(project_id), above
        project = db.session.query(ProjectModel).options(
            joinedload(ProjectModel.attributes)
        ).filter(ProjectModel.project_id == project_id).first()
        if not project:
            return {'message': 'Project not found.'}, 404

        # Get all samples related to the project
        samples = db.session.query(Sample).filter(Sample.project_id == project_id).all()
        if not samples:
            return [], 200
        return [sample.to_dict() for sample in samples]

#    def post(self, project_id):
#        ''' POST /projects/<project_id>/samples '''
        # This is a placeholder for the actual implementation
        # You would typically create a new sample related to the project here
#        return {'message': 'Create sample for project not implemented yet.'}, 501
