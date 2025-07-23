"""
Initialize the database and populate it 
with default (or test) data.
"""
from sqlmodel import Session
from core.db import create_db_and_tables, engine
from core.deps import SessionDep
from core.logger import logger
import api.project.services as project_services
import api.project.models

from api.project.models import (
  ProjectCreate,
  Attribute
)

def create_default_projects(*, session: SessionDep):
  """
  Create some default project data
  """
  project1 = ProjectCreate(
    name="Eric's test project",
    attributes=[
      Attribute(
        key="Owner",
        value="Eric"
      ),
      Attribute(
        key="App",
        value="NGS360"
      )
    ]
  )
  project_services.create_project(
    session=session,  
    project_in=project1
  )

  project2 = ProjectCreate(
    name="Another test project",
    attributes=[
      Attribute(
        key="Owner",
        value="Eric"
      ),
      Attribute(
        key="App",
        value="Locker"
      )
    ]
  )
  project_services.create_project(
    session=session,  
    project_in=project2
  )

  project3 = ProjectCreate(
    name="Project3 without attributes",
  )
  project_services.create_project(
    session=session,  
    project_in=project3
  )


def main():
  logger.info("Create tables...")
  create_db_and_tables()
  # logger.info("Creating default projects")
  #with Session(engine) as session:
  #  create_default_projects(session=session)


if __name__ == "__main__":
  main()