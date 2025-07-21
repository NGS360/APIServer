"""
Services for the Project API
"""
from datetime import datetime
from typing import List, Literal
from fastapi import HTTPException, status
from pydantic import PositiveInt
from pytz import timezone
from sqlmodel import Session, func, select
from core.logger import logger

from api.project.models import (
   Project,
   ProjectAttribute,
   ProjectCreate,
   ProjectPublic,
   ProjectsPublic
)

def generate_project_id(*, session: Session) -> str:
  '''
  Generate a unique project_id.
  This ID could be anything as long as its unique and human-readable.
  In this case, we generate an ID with the format P-YYYYMMDD-NNNN
  '''
  # Prefix out of todays date (e.g., "P-20250717-")
  now = datetime.now(timezone('US/Eastern'))
  prefix = f"P-{now:%Y%m%d}-"

  # Find last project with today's date
  project = session.exec(
     select(Project)
      .where(Project.project_id.like(f"{prefix}%"))
      .order_by(Project.project_id.desc())
      .limit(1)
  ).one_or_none()

  if not project:
     return f"{prefix}0001"

  # Increment the suffix (part after the second hyphen)
  suffix = int(project.project_id.split('-')[2]) + 1
  return f"{prefix}{suffix:04d}"


def create_project(*, session: Session, project_in: ProjectCreate) -> Project:
   """
   Create a new project with optional attributes.
   """
   # Create initial project
   project = Project(
      project_id=generate_project_id(session=session),
      name=project_in.name
   )
   session.add(project)
   session.flush()

   # Handle attribute mapping
   if project_in.attributes:
      # Prevent duplicate keys
      seen = set()
      keys = [attr.key for attr in project_in.attributes]
      dups = [k for k in keys if k in seen or seen.add(k)]
      if dups:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Duplicate keys ({', '.join(dups)}) are not allowed in project attributes."
         )

      # Parse and create project attributes
      # linking to new project
      project_attributes = [
         ProjectAttribute(
            project_id=project.id, 
            key=attr.key,
            value=attr.value
         )
         for attr in project_in.attributes
      ]

      # Update database with attribute links
      session.add_all(project_attributes)

   # With orm_mode=True, attributes will be eagerly loaded
   # and mapped to ProjectPublic via response model
   session.commit()
   session.refresh(project)
   logger.info(f"Created project {project.project_id}")
   return project

def get_projects(
      *, 
      session: Session, 
      page: PositiveInt, 
      per_page: PositiveInt, 
      sort_by: str,
      sort_order: Literal['asc', 'desc']
   ) -> List[Project]:
   """
   Returns all projects from the database along
   with pagination information.
   """
   # Get total project count
   count = session.exec(
      select(func.count()).select_from(Project)
   ).one()

   # Compute total pages
   total_pages = (count + per_page - 1) // per_page # Ceiling division

   # Determine sort field and direction
   sort_field = getattr(Project, sort_by, Project.id)
   sort_direction = sort_field.asc() if sort_order == 'asc' else sort_field.desc()

   # Get project selection
   projects = session.exec(
      select(Project)
         .order_by(sort_direction)
         .limit(per_page)
         .offset((page - 1) * per_page)
   ).all()

   # Map to public project
   public_projects = [
      ProjectPublic(
         project_id=project.project_id,
         name=project.name,
         attributes=project.attributes
      )
      for project in projects
   ]

   return ProjectsPublic(
      data=public_projects,
      total_items=count,
      total_pages=total_pages,
      current_page=page,
      per_page=per_page,
      has_next=page < total_pages,
      has_prev=page > 1
   )

def get_project_by_project_id(session: Session, project_id: str) -> Project:
   """
   Returns a single project by its project_id.
   Note: This is different from its internal "id".
   """
   project = session.exec(
      select(Project)
         .where(Project.project_id == project_id)
   ).first()
   
   if not project:
      raise HTTPException(
         status_code=status.HTTP_404_NOT_FOUND,
         detail=f"Project {project_id} not found."
      )
   
   return project