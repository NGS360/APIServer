''' 
Database Model

Project table is the main table that stores the project name.
ProjectAttribute table stores the key-value attributes for each project.
Project model has a one-to-many relationship with ProjectAttribute model.
'''
# pylint: disable=too-few-public-methods
from typing import Optional
from sqlalchemy import ForeignKey
import sqlalchemy as sa
import sqlalchemy.orm as so

from apiserver.extensions import DB as db
class Project(db.Model):
    ''' Project '''
    __tablename__ = 'project'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)

    attributes = so.relationship(
        'ProjectAttribute', back_populates='project', cascade="all, delete-orphan")

    def to_dict(self):
        ''' Convert to dictionary including attributes '''
        data = {column.name: getattr(self, column.name) for column in self.__table__.columns}
        # Include dynamic attributes
        data['attributes'] = {attr.key: attr.value for attr in self.attributes}
        return data

    def __repr__(self):
        return f'<Project {self.name}>'

class ProjectAttribute(db.Model):
    ''' Key-Value attributes for Project '''
    __tablename__ = 'project_attribute'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    project_id: so.Mapped[int] = so.mapped_column(ForeignKey('project.id'), nullable=False)
    key: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    value: so.Mapped[str] = so.mapped_column(sa.String(1024), nullable=False)

    project = so.relationship('Project', back_populates='attributes')

    def to_dict(self): # pylint: disable=missing-function-docstring
        return {self.key: self.value}

    def __repr__(self):
        return f'<ProjectAttribute {self.key}={self.value}>'
