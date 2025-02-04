''' Database Model '''
# pylint: disable=too-few-public-methods
import sqlalchemy as sa
import sqlalchemy.orm as so

from apiserver import db

class Project(db.Model):
    ''' Project '''
    __tablename__ = 'project'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64), index=True, unique=True)
    description: so.Mapped[str] = so.mapped_column(sa.String(256))

    def __repr__(self):
        return f'<Project {self.name}>'
