"""
Main entrypoint for the FastAPI server
"""

import logging

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import text
from core.lifespan import lifespan
from core.config import get_settings
from core.deps import SessionDep
from core.middleware import RequestContextMiddleware

from api.auth.deps import get_current_active_user
from api.auth.routes import router as auth_router
from api.auth.oauth_routes import router as oauth_router
from api.actions.routes import router as actions_router
from api.chat.routes import router as chat_router
from api.files.routes import router as files_router
from api.jobs.routes import router as jobs_router
from api.manifest.routes import router as manifest_router
from api.project.routes import router as project_router
from api.qcmetrics.routes import router as qcmetrics_router
from api.runs.routes import router as runs_router
from api.samples.routes import router as samples_router
from api.search.routes import router as search_router
from api.settings.routes import router as settings_router
from api.vendors.routes import router as vendors_router
from api.workflow.routes import router as workflow_router
from api.pipeline.routes import router as pipeline_router
from api.platforms.routes import router as platforms_router
from api.users.routes import router as users_router
from api.rbac.routes import router as rbac_router

logger = logging.getLogger(__name__)


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
            input_val = error.get("input")
            # Ensure the value is JSON-serializable (e.g., convert bytes to string)
            if isinstance(input_val, bytes):
                input_val = input_val.decode("utf-8", errors="replace")
            formatted_error["received"] = input_val

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
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": message,
            "hint": hint,
            "errors": formatted_errors,
            "docs_url": f"{request.base_url}docs#{request.url.path.replace('/', '-').strip('-')}"
        }
    )


# CORS settings to allow client-server communication
# Set with env variable
origins = [origin for origin in [get_settings().client_origin] if origin is not None]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request id + structured access logging. Added AFTER CORSMiddleware, so it sits
# OUTSIDE it: Starlette applies middleware in reverse registration order, so the
# last added runs first. That is deliberate -- it means CORS preflight responses
# and any error raised inside CORS handling are still logged, and every response
# carries X-Request-ID.
app.add_middleware(RequestContextMiddleware)


# Create a simple health check endpoint
@app.get("/", tags=["index"])
def root():
    return {"message": "Welcome to the NGS360 API! Visit /docs for API documentation."}


@app.get("/api/health", tags=["health"])
def health_check(session: SessionDep):
    """Health check that also probes database connectivity.

    Returns 503 when the database is unreachable so the load balancer marks the
    target unhealthy instead of routing traffic to an instance that can't serve
    DB-backed requests (e.g. new instances that lack RDS security-group access).

    Takes the session through the normal dependency rather than opening one on
    the module-level engine. In production the two are the same object, so the
    probe is unchanged; in tests they are not, and building the engine at import
    time meant this endpoint dialled whichever deployed database .env happened
    to name. `get_db` only constructs the Session -- the connection is made by
    the execute below -- so an unreachable database still surfaces here as a
    clean 503 rather than a 500 from dependency resolution.
    """
    try:
        session.execute(text("SELECT 1"))
    except Exception as e:
        logger.exception("Health check database probe failed: %s", e)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "message": "Database connectivity check failed."},
        )
    return {"status": "ok", "message": "NGS360 API is running."}


# REST routers
# Add each api/feature folder here
API_PREFIX = "/api/v1"

# Authentication routers (no auth required)
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(oauth_router, prefix=API_PREFIX)

# Feature routers.
#
# Every one of these requires an authenticated caller, applied here at the
# include rather than on each route. 2026-10-14: 28 data routes carried no
# authentication dependency at all -- among them GET /runs/{run_id} at 393,818
# requests a week, GET /projects/{project_id}/samples, and POST
# /files/upload, which is a *write*. They were 99.8% authenticated in practice,
# so the exposure was latent rather than exercised, but nothing enforced it.
#
# Applied at the router because the alternative is twenty-eight separate
# decorators that a twenty-ninth route can silently fail to copy. The split
# above is the whole policy: an endpoint is reachable anonymously if and only if
# it sits in the authentication routers, and tests/test_route_coverage.py
# asserts exactly that.
#
# Routes already carrying CurrentUser or a permission guard are unaffected --
# FastAPI resolves a dependency once per request, so the duplicate is free.
AUTHENTICATED = [Depends(get_current_active_user)]

app.include_router(actions_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(chat_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(files_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(jobs_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(manifest_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(project_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(qcmetrics_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(runs_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(samples_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(search_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(settings_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(vendors_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(workflow_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(pipeline_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(platforms_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(users_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)
app.include_router(rbac_router, prefix=API_PREFIX, dependencies=AUTHENTICATED)


if __name__ == "__main__":
    # For debugging purposes
    import uvicorn
    import os

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run("main:app", host=host, port=port, reload=True)
