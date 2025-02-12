'''
Workflow Execution Platforms API
'''
from flask import jsonify, request
from flask_restx import Namespace, Resource

platforms = [
    { 'id': 1, 'name': 'Velsera' },
    { 'id': 2, 'name': 'Arvados' },
]

NS = Namespace('platforms', description='Workflow Execution Platforms API')

@NS.route('')
class Platforms(Resource):
    ''' Platforms API '''

    def get(self):
        ''' GET /platforms '''
        return jsonify(platforms)

    def post(self):
        ''' POST /platforms '''
        platforms.append(request.get_json())
        return '', 204
