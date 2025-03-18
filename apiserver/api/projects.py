'''
Projects API
'''
from flask import jsonify, request
from flask_restx import Namespace, Resource

projects = [
    { 'id': 1, 'name': 'test project'},
    { 'id': 2, 'name': 'test 2 project'},
    { 'id': 3, 'name': 'test 3 project'},
]

NS = Namespace('projects', description='Projects API')

@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects '''
        return jsonify(projects)

    def post(self):
        ''' POST /projects '''
        projects.append(request.get_json())
        return '', 204
