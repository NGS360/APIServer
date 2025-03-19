'''
Projects API
'''
from flask import jsonify, request, current_app
from flask_restx import Namespace, Resource, fields

from apiserver import DB as db
from apiserver.models import Project, ProjectSchema

from marshmallow import ValidationError

NS = Namespace('projects', description='Projects API')

# Error Handler for Marshmallow Validation Errors
@NS.errorhandler(ValidationError)
def handle_marshmallow_error(error):
    return {"message": error.messages}, 400

# Marshmallow Schema
project_schema = ProjectSchema()

# Flask-RESTx Model for Swagger Docs
project_model = NS.model("Project", {
    "name": fields.String(required=True, description="Project name"),
    "description": fields.String(required=False, description="Project description")
})
@NS.route('')
class Projects(Resource):
    ''' Projects API '''

    def get(self):
        ''' GET /projects '''
        projects = db.session.query(Project).all()
        current_app.logger.debug(projects)
        return project_schema.dump(projects, many=True)

    @NS.expect(project_model)
    def post(self):
        ''' POST /projects '''
        try:
            validated_data = project_schema.load(request.json)
            project = Project(**validated_data)
            db.session.add(project)
            db.session.commit()
            return project_schema.dump(project), 201
        except ValidationError as error:
            return error.messages, 400

