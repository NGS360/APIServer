'''
Projects API
'''
from flask import jsonify, request, current_app
from flask_restx import Namespace, Resource

from apiserver import DB as db
from apiserver.models import Project

NS = Namespace('projects', description='Projects API')

@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects '''
        projects = db.session.query(Project).all()
        current_app.logger.debug(projects)
        return [project.to_dict() for project in projects]

    def post(self):
        ''' POST /projects '''
        return '', 201

