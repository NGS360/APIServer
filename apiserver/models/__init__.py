''' Database Model '''
# pylint: disable=too-few-public-methods
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so

from apiserver import DB as db
class Project(db.Model):
    ''' Project '''
    __tablename__ = 'project'
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))

    def to_dict(self):
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self):
        return f'<Project {self.name}>'

