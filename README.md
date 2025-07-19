# NGS360 API Server

This repository contains the code for the NGS360 API server, which provides a RESTful API for accessing and managing data related to Next Generation Sequencing (NGS) projects.

It uses FastAPI for building the API and SQLAlchemy for database interactions.

## Directory structure

- `main.py`: The main entry point for the FastAPI application. Configure routes, middleware and lifespan events here.
- `core/`: Contains core configurations, settings, and utilities used across the application.
- `api/{feature}/`: Contains the API models, routes, and services for each `{feature}`.
  - `models.py`: Defines the data models used in the API, including Pydantic models for request and response validation.
  - `routes.py`: Contains the FastAPI routes for handling HTTP requests related to the feature.
  - `services.py`: Contains the business logic and database interactions for the feature.
