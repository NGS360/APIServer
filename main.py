"""
Main entrypoint for the FastAPI server
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from core.lifespan import lifespan
from core.config import get_settings

from api.auth.routes import router as auth_router
from api.auth.oauth_routes import router as oauth_router
from api.files.routes import router as files_router
from api.jobs.routes import router as jobs_router
from api.pipelines.routes import router as pipelines_router
from api.project.routes import router as project_router
from api.runs.routes import router as runs_router
from api.samples.routes import router as samples_router
from api.search.routes import router as search_router
from api.settings.routes import router as settings_router
from api.vendors.routes import router as vendors_router
from api.workflow.routes import router as workflow_router
from api.manifest.routes import router as manifest_router


# Customize route id's
# Helpful for creating sensible names in the client
def custom_generate_unique_id(route: APIRoute):
    """ Generate unique route IDs based on route name """
    return f"{route.name}"  # these must be unique


# Create schema & router
app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)


# Generic validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Generic validation error handler that provides detailed, actionable error messages
    for any endpoint with validation errors.
    """
    errors = exc.errors()

    # Build a user-friendly error response
    formatted_errors = []
    for error in errors:
        # Get the field path (e.g., ['body', 'email'] -> 'email')
        field_path = " -> ".join(str(loc) for loc in error["loc"] if loc != "body")

        formatted_error = {
            "field": field_path or "body",
            "message": error["msg"],
            "type": error["type"],
        }

        # Add input value if available (helps debugging)
        if "input" in error:
            formatted_error["received"] = error.get("input")

        formatted_errors.append(formatted_error)

    # Determine if the entire body is missing
    is_missing_body = any(
        error["type"] == "missing" and "body" in error["loc"]
        for error in errors
    )

    if is_missing_body:
        message = "Request body is required but was not provided"
        hint = f"Please send a JSON body with your request to {request.method} {request.url.path}"
    else:
        message = "Validation error in request"
        hint = "Please check the errors below and correct your request"

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": message,
            "hint": hint,
            "errors": formatted_errors,
            "docs_url": f"{request.base_url}docs#{request.url.path.replace('/', '-').strip('-')}"
        }
    )


# CORS settings to allow client-server communication
# Set with env variable
origins = [get_settings().client_origin]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Create a simple health check endpoint
@app.get("/", tags=["index"])
def root():
    return {"message": "Welcome to the NGS360 API! Visit /docs for API documentation."}


@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok", "message": "NGS360 API is running."}


# REST routers
# Add each api/feature folder here
API_PREFIX = "/api/v1"

# Authentication routers (no auth required)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(oauth_router, prefix=API_PREFIX)

# Feature routers
app.include_router(files_router, prefix=API_PREFIX)
app.include_router(jobs_router, prefix=API_PREFIX)
app.include_router(project_router, prefix=API_PREFIX)
app.include_router(pipelines_router, prefix=API_PREFIX)
app.include_router(runs_router, prefix=API_PREFIX)
app.include_router(samples_router, prefix=API_PREFIX)
app.include_router(search_router, prefix=API_PREFIX)
app.include_router(settings_router, prefix=API_PREFIX)
app.include_router(vendors_router, prefix=API_PREFIX)
app.include_router(manifest_router, prefix=API_PREFIX)
app.include_router(workflow_router, prefix=API_PREFIX)


if __name__ == "__main__":
    # For debugging purposes
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
