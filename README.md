# NGS360 API Server

This repository contains the code for the NGS360 API server, which provides a RESTful API for accessing and managing data related to Next Generation Sequencing (NGS) projects.

It uses FastAPI for building the API and SQLModel (SQLAlchemy + Pydantic) for database interactions.

## Directory Structure

- `main.py`: The main entry point for the FastAPI application. Configure routes, middleware and lifespan events here.
- `core/`: Contains core configurations, settings, and utilities used across the application.
- `api/{feature}/`: Contains the API models, routes, and services for each `{feature}`.
  - `models.py`: Defines the data models used in the API, including Pydantic models for request and response validation.
  - `routes.py`: Contains the FastAPI routes for handling HTTP requests related to the feature.
  - `services.py`: Contains the business logic and database interactions for the feature.

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

---

## Install

This application uses pyproject.toml and uv as the package manager.

### Development

To install this for development, use:

```bash
uv sync
```

This will create a Python virtual environment in .venv (by default) using the version of python listed in .python-version, and install the dependencies listed in pyproject.toml.

Make sure necessary environment variables are defined or present in .env, as needed in core/config.py, then run the service:

```bash
source .venv/bin/activate
fastapi dev main.py
```

### Unit Tests

```bash
uv sync --extra dev
pytest -xvs --cov
coverage html
open htmlcov/index.html
```

See [tests/TESTING_GUIDE.md](tests/TESTING_GUIDE.md) for detailed testing documentation.

### Docker Stack

Use the stack as described in docker-compose.yml to launch all components.

#### Environment Variables for Docker

The docker-compose.yml file uses environment variable substitution for AWS credentials. You have two options:

**Option 1: Use a .env file (Recommended for development)**

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your AWS credentials:
   ```bash
   AWS_ACCESS_KEY_ID=your_actual_access_key
   AWS_SECRET_ACCESS_KEY=your_actual_secret_key
   AWS_REGION=us-east-1
   ```

3. Launch the stack:
   ```bash
   docker-compose up
   ```

**Option 2: Export environment variables (Recommended for CI/CD)**

```bash
export AWS_ACCESS_KEY_ID=your_actual_access_key
export AWS_SECRET_ACCESS_KEY=your_actual_secret_key
export AWS_REGION=us-east-1
docker-compose up
```

**Note:** If no environment variables are set, the docker-compose file will use default values (`admin`/`admin`) suitable for local OpenSearch development.

#### OpenSearch SSL Configuration

The application supports different OpenSearch configurations for development and production:

**Local Development (Docker Compose)**
- Uses HTTP (no SSL) with security plugin disabled
- Set in `docker-compose.yml`:
  ```yaml
  - OPENSEARCH_USE_SSL=false
  - OPENSEARCH_VERIFY_CERTS=false
  ```

**Production (AWS OpenSearch Service)**
- Uses HTTPS with SSL/TLS enabled
- Configure in your production `.env` file or secrets manager:
  ```bash
  OPENSEARCH_USE_SSL=true
  OPENSEARCH_VERIFY_CERTS=true
  OPENSEARCH_USER=your_username
  OPENSEARCH_PASSWORD=your_password
  ```

These settings are controlled by environment variables and can be adjusted per environment without code changes.

---

## Documentation

Additional documentation is available in the `docs/` directory:

- [AUTHENTICATION.md](docs/AUTHENTICATION.md) - Authentication setup and configuration
- [OAuth2_Authorization_Code_Grant_Flow.md](docs/OAuth2_Authorization_Code_Grant_Flow.md) - OAuth2 flow details
- [SETUP.md](docs/SETUP.md) - Environment setup instructions
