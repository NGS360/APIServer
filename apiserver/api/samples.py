'''
Samples API
'''
from flask import jsonify, request
from flask_restx import Namespace, Resource

samples = [
    { 'id': 1, 'name': 'sampleA', 'assay': 'RNA-Seq', 'project': 'ABC' },
    { 'id': 2, 'name': 'sampleB', 'assay': 'RNA-Seq', 'project': 'ABC' },
    { 'id': 3, 'name': 'sampleC', 'assay': 'WES', 'project': 'DEF' },
]

NS = Namespace('samples', description='Samples API')

@NS.route('')
class Samples(Resource):
    ''' Samples API '''

    def get(self):
        ''' GET /Samples '''
        return jsonify(samples)

    def post(self):
        ''' POST /samples '''
        samples.append(request.get_json())
        return '', 204
