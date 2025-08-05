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

```{text}
APIServer/
├── main.py                  # Application entry point
├── core/                    # Core functionality 
│   ├── config.py            # Configuration settings
│   ├── db.py                # Database connection
│   ├── deps.py              # Dependency injection
│   ├── init_db.py           # Database initialization
│   └── lifespan.py          # Application lifecycle
└── api/                     # API endpoints by feature
    ├── project/             # Project feature module
        ├── models.py        # Data models
        ├── routes.py        # API routes/endpoints
        └── services.py      # Business logic
    ├── samples/
    ├── files/
    ├── platforms/
    ├── users/
    └── workflows/
```

## Key Components

### FastAPI Setup (main.py)

- The entry point creates the FastAPI application
- Sets up CORS middleware for client communication
- Includes routers for different API features
- Configures the application lifespan for startup/shutdown tasks

### Database Integration (core/)

- Uses SQLModel (SQLAlchemy + Pydantic) for database operations
- Connects to a MySQL database (configured via environment variables)
- Database initialization happens on application startup
- Clean database session management through dependency injection

### Project API (api/v1/project/)

- **Models**:
  - `Project` - Main project entity with UUID primary key and human-readable `project_id`
  - `ProjectAttribute` - Key-value attributes associated with projects
  - Separate models for input (`ProjectCreate`) and output (`ProjectPublic`, `ProjectsPublic`)

- **Endpoints**:
  - `POST /project/create_project` - Create a new project with optional attributes
  - `GET /project/read_projects` - List projects with pagination and sorting
  - `GET /project/{project_id}` - Get a single project by its project_id

- **Services**:
  - Project ID generation with format `P-YYYYMMDD-NNNN`
  - Project creation with attribute mapping
  - Paginated project retrieval
  - Single project lookup by project_id

### Sample API (api/v1/sample/)

- **Models**:
  - `Sample` - Main sample entity with UUID primary key, sample_id, project_id foreign-key to Project
  - `SampleAttribute` - Key-value attributes associated with samples
  - Separate models for input (`SampleCreate`) and output (`SamplePublic`, `SamplesPublic`)

- **Endpoints**:
  - `POST /samples` - Create a new sample with optional attributes
  - `GET /samples` - List samples with pagination and sorting
  - `GET /samples/{sample_id}` - Get a single sample by its sample_id

- **Services**:
  - TBD 1
  - TBD 2
  - TBD 3

## Modern FastAPI Patterns Used

1. **Dependency Injection**
   - Database sessions injected into endpoints using `Depends`
   - Type aliases used for cleaner parameter annotations (`SessionDep`)

2. **Pydantic Models**
   - Clear separation between database models, input models, and output models
   - Validation built into models

3. **Application Lifecycle Management**
   - `lifespan` context manager for startup/shutdown procedures
   - Database initialized on startup and dropped on shutdown

4. **SQLModel Integration**
   - Modern ORM combining SQLAlchemy and Pydantic
   - Relationship management between projects and attributes

5. **Environment-based Configuration**
   - Settings loaded from environment variables
   - Pydantic-based configuration with computed values

6. **Error Handling**
   - Proper HTTP exceptions with status codes and descriptive messages
   - Validation of business rules (e.g., unique attribute keys)

## Improvements Over Traditional REST APIs

This FastAPI implementation represents several improvements over traditional approaches:

1. Strong typing throughout the codebase
2. Automatic API documentation generation
3. Dependency injection system for cleaner endpoint handlers
4. Modern async support (though not heavily used in this codebase)
5. Integrated validation via Pydantic models
6. Clear separation of data models, routes, and business logic

The application is designed to be modular and extensible, with new features easily added by creating additional modules in the `api/` directory and including their routers in `main.py`.

## Install

This application uses pyproject.toml and uv as the package manager.

### Development

To install this for development, use:

```{bash}
uv sync
```

This will create a Python virtual environment in .venv (by default) using the version of python listed in .python-version, and install the dependencies listed in pyproject.toml.

Make sure necessary environment variables are defined or present in .env, as need in core/config.py, then run the service:

```{bash}
source .venv/bin/activate
fastapi dev main.py
```

### Unit Tests

```{bash}
uv pip install httpx pytest pvtest-cov
pytest -xvs --cov
coverage html
open htmlcov/index.html
```
