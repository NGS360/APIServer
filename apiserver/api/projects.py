'''
Projects API
'''
from flask import jsonify, request, current_app
from flask_restx import Namespace, Resource

from apiserver.models import Project
from apiserver.extensions import DB as db

NS = Namespace('projects', description='Projects API')

@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects '''
        projects = Project.query.all()
        current_app.logger.debug('Projects: %s', projects)
        if projects:
            return jsonify([project.to_dict() for project in projects])
        return jsonify([])

    def post(self):
        ''' POST /projects '''
        data = request.get_json()
        project = Project(**data)
        db.session.add(project)
        db.session.commit()
        current_app.logger.debug('Project: %s added to db', project.to_dict())
        return project.to_dict(), 201
