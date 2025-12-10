"""
Main entrypoint for the FastAPI server
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from core.lifespan import lifespan
from core.config import get_settings

from api.files.routes import router as files_router
from api.project.routes import router as project_router
from api.runs.routes import router as runs_router
from api.samples.routes import router as samples_router
from api.search.routes import router as search_router
from api.vendors.routes import router as vendors_router


# Customize route id's
# Helpful for creating sensible names in the client
def custom_generate_unique_id(route: APIRoute):
    """ Generate unique route IDs based on route name """
    return f"{route.name}"  # these must be unique


# Create schema & router
app = FastAPI(
    lifespan=lifespan,
    generate_unique_id_function=custom_generate_unique_id
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

# Mount static files for React app assets (JS, CSS, images, etc.)
# This serves files from /assets/*, /favicon.*, etc.
app.mount(
    "/assets",
    StaticFiles(directory="static/assets"),
    name="static-assets"
)

# REST routers
# Add each api/feature folder here
API_PREFIX = "/api/v1"

app.include_router(files_router, prefix=API_PREFIX)
app.include_router(project_router, prefix=API_PREFIX)
app.include_router(runs_router, prefix=API_PREFIX)
app.include_router(samples_router, prefix=API_PREFIX)
app.include_router(search_router, prefix=API_PREFIX)
app.include_router(vendors_router, prefix=API_PREFIX)


# Health check endpoint for monitoring
@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok", "message": "NGS360 API is running"}


# Serve static files (favicon, robots.txt, manifest.json)
@app.get("/favicon.{ext:path}", include_in_schema=False)
async def favicon(ext: str):
    return FileResponse(f"static/favicon.{ext}")


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    return FileResponse("static/robots.txt")


@app.get("/manifest.json", include_in_schema=False)
async def manifest():
    return FileResponse("static/manifest.json")


# Catch-all route to serve React app for client-side routing
# This MUST be last to avoid catching API routes
@app.get("/{full_path:path}", include_in_schema=False)
async def serve_react_app(full_path: str):
    """
    Serve the React app for all non-API routes.
    This enables client-side routing with TanStack Router.
    """
    return FileResponse("static/index.html")

if __name__ == "__main__":
    # For debugging purposes
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
