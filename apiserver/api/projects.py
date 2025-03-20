'''
Projects API
'''
from flask import jsonify, request
from flask_restx import Namespace, Resource

from ..models import Project
from ..api import db

NS = Namespace('projects', description='Projects API')

@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects '''
        projects = Project.query.all()
        return jsonify(projects)

    def post(self):
        ''' POST /projects '''
        data = request.get_json()
        project = Project(**data)
        db.session.add(project)
        db.session.commit()
        return jsonify(project), 201
