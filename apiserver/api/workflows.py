'''
Workflows API
'''
from flask import jsonify, request
from flask_restx import Namespace, Resource

workflows = [
    { 'id': 1, 'name': 'RNA-Seq', },
    { 'id': 2, 'name': 'WES', },
]

NS = Namespace('workflows', description='Workflows API')

@NS.route('')
class Workflows(Resource):
    ''' Workflows API '''

    def get(self):
        ''' GET /workflows '''
        return jsonify(workflows)

    def post(self):
        ''' POST /workflows '''
        workflows.append(request.get_json())
        return '', 204
