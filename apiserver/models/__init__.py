''' 
Database Model

Project table is the main table that stores the project name.
ProjectAttribute table stores the key-value attributes for each project.
Project model has a one-to-many relationship with ProjectAttribute model.
'''
# pylint: disable=too-few-public-methods
from datetime import datetime
from pytz import timezone

from sqlalchemy import ForeignKey
import sqlalchemy as sa
import sqlalchemy.orm as so

from apiserver.extensions import DB as db
class Project(db.Model):
    ''' Project '''
    __tablename__ = 'project'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)

    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(64), nullable=False, index=True, unique=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)

    attributes = so.relationship(
        'ProjectAttribute', back_populates='project', cascade="all, delete-orphan")

    @staticmethod
    def generate_project_id():
        '''
        Generate a unique project_id.
        This ID could be anything as long as its unique and human-readable.
        In this case, we generate an ID with the format P-YYYYMMDD-NNNN
        '''
        current_date = datetime.now(timezone('US/Eastern'))
        project_prefix = f"P-{current_date.year:02d}{current_date.month:02d}{current_date.day:02d}-"

        # Find last project with today's date
        project = db.session.query(Project).filter(
            Project.project_id.like(f'{project_prefix}%')).order_by(
                Project.project_id.desc()).first()
        if not project:
            project_id = f'{project_prefix}0001'
        else:
            project_id = int(project.project_id.split('-')) + 1
            project_id = f'{project_prefix}{project_id:04d}'

        return project_id

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

class Sample(db.Model):
    ''' Sample '''
    __tablename__ = 'sample'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)

    project_id: so.Mapped[int] = so.mapped_column(ForeignKey('project.id'), nullable=False)
    sample_id: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)

    attributes = so.relationship(
        'SampleAttribute', back_populates='sample', cascade="all, delete-orphan")

    def to_dict(self):
        ''' Convert to dictionary including attributes '''
        data = {column.name: getattr(self, column.name) for column in self.__table__.columns}
        # Include dynamic attributes
        data['attributes'] = {attr.key: attr.value for attr in self.attributes}
        return data

class SampleAttribute(db.Model):
    ''' Key-Value attributes for Sample '''
    __tablename__ = 'sample_attribute'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    sample_id: so.Mapped[int] = so.mapped_column(ForeignKey('sample.id'), nullable=False)
    key: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    value: so.Mapped[str] = so.mapped_column(sa.String(1024), nullable=False)

    sample = so.relationship('Sample', back_populates='attributes')

    def to_dict(self): # pylint: disable=missing-function-docstring
        return {self.key: self.value}

    def __repr__(self):
        return f'<SampleAttribute {self.key}={self.value}>'
