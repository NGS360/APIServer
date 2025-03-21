'''
Projects API
'''
from flask import request
from flask_restx import Namespace, Resource

from apiserver.models import Project
from apiserver.extensions import DB as db

NS = Namespace('projects', description='Projects API')

@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects '''
        projects = db.session.query(Project).all()
        return [project.to_dict() for project in projects]

    def post(self):
        ''' POST /projects '''
        data = request.get_json()
        project = Project(**data)
        db.session.add(project)
        db.session.commit()
        return project.to_dict(), 201
