"""
Main entrypoint for the FastAPI server
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from core.lifespan import lifespan
from core.config import get_settings

from api.files.routes import router as files_router
from api.project.routes import router as project_router
from api.runs.routes import router as runs_router
from api.samples.routes import router as samples_router
from api.search.routes import router as search_router
from api.tools.routes import router as tools_router
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

app.include_router(files_router, prefix=API_PREFIX)
app.include_router(project_router, prefix=API_PREFIX)
app.include_router(runs_router, prefix=API_PREFIX)
app.include_router(samples_router, prefix=API_PREFIX)
app.include_router(search_router, prefix=API_PREFIX)
app.include_router(tools_router, prefix=API_PREFIX)
app.include_router(vendors_router, prefix=API_PREFIX)
app.include_router(manifest_router, prefix=API_PREFIX)
app.include_router(workflow_router, prefix=API_PREFIX)


if __name__ == "__main__":
    # For debugging purposes
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
