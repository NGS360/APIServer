'''
Users API
'''
from flask import jsonify, request
from flask_restx import Namespace, Resource

users = [
    { 'id': 1, 'username': 'user1', 'email': 'user1@someplace.com' },
    { 'id': 2, 'username': 'user2', 'assay': 'user2@anotherplace.com' },
]

NS = Namespace('users', description='Users API')

@NS.route('')
class Users(Resource):
    ''' Users API '''

    def get(self):
        ''' GET /users '''
        return jsonify(users)

    def post(self):
        ''' POST /users '''
        users.append(request.get_json())
        return '', 204
