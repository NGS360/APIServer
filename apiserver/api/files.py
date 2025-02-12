'''
Samples API
'''
from flask import jsonify, request
from flask_restx import Namespace, Resource

files = [
    { 'id': 1, 'sample': 'sampleA', 'files': ['sampleA_R1.fq.gz', 'sampleA_R2.fq.gz'] },
    { 'id': 2, 'sample': 'sampleB', 'files': ['sampleB_R1.fq.gz', 'sampleB_R2.fq.gz'] },
    { 'id': 3, 'sample': 'sampleC', 'files': ['sampleC_R1.fq.gz'] },
]

NS = Namespace('files', description='Files API')

@NS.route('')
class Files(Resource):
    ''' Files API '''

    def get(self):
        ''' GET /files '''
        return jsonify(files)

    def post(self):
        ''' POST /files '''
        files.append(request.get_json())
        return '', 204
