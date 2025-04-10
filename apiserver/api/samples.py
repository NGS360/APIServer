'''
Samples API
'''
from flask_restx import Namespace, Resource

NS = Namespace('samples', description='Samples API')

@NS.route('')
class Samples(Resource):
    ''' Samples API '''

    def get(self):
        ''' GET /Samples '''

    def post(self):
        ''' POST /samples '''
