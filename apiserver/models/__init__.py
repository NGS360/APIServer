''' Database Model '''
# pylint: disable=too-few-public-methods
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so

from marshmallow import Schema, fields

from apiserver import DB as db
class Project(db.Model):
    ''' Project '''
    __tablename__ = 'project'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))

    def __repr__(self):
        return f'<Project {self.name}>'

class ProjectSchema(Schema):
    id = fields.Integer(dump_only=True)
    name = fields.String(required=True)
    description = fields.String(required=False)

