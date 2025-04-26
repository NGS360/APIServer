'''
Projects API
'''
from flask import request, current_app, url_for
from flask_restx import Namespace, Resource, reqparse

from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from apiserver.models import Project as ProjectModel, ProjectAttribute, Sample
from apiserver.extensions import DB as db

NS = Namespace('projects', description='Projects API')

@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects

        Returns a paginated list of projects.

        Query Parameters:
            page (int): Page number (1-indexed, default: 1)
            per_page (int): Number of items per page (default: 20)
            sort_by (str): Field to sort by (default: 'id')
            sort_order (str): Sort order ('asc' or 'desc', default: 'asc')
        '''
        # Parse pagination parameters
        parser = reqparse.RequestParser()
        parser.add_argument('page', type=int, default=1, help='Page number (1-indexed)')
        parser.add_argument('per_page', type=int, default=20, help='Number of items per page')
        parser.add_argument('sort_by', type=str, default='id', help='Field to sort by')
        parser.add_argument('sort_order', type=str, default='asc', choices=('asc', 'desc'),
                           help='Sort order (asc or desc)')
        args = parser.parse_args()

        # Validate pagination parameters
        page = max(1, args['page'])  # Ensure page is at least 1
        per_page = min(max(1, args['per_page']), 100)  # Ensure per_page is between 1 and 100

        # Determine sort field and direction
        sort_field = getattr(ProjectModel, args['sort_by'], ProjectModel.id)
        sort_direction = sort_field.asc() if args['sort_order'] == 'asc' else sort_field.desc()

        try:
            # Get total count for pagination metadata
            total_count = db.session.query(ProjectModel).count()

            # Get paginated projects with eager loading of attributes
            query = db.session.query(ProjectModel).options(joinedload(ProjectModel.attributes))
            query = query.order_by(sort_direction)
            projects = query.limit(per_page).offset((page - 1) * per_page).all()

            # Calculate pagination metadata
            total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

            # Prepare response with pagination metadata
            response = {
                'projects': [project.to_dict() for project in projects],
                'pagination': {
                    'total_items': total_count,
                    'total_pages': total_pages,
                    'current_page': page,
                    'per_page': per_page,
                    'has_next': page < total_pages,
                    'has_prev': page > 1
                }
            }

            return response

        except Exception as error:
            current_app.logger.error('Error retrieving projects: %s', error)
            return {'message': 'Error retrieving projects.'}, 500

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
