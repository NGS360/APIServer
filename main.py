"""
Main entrypoint for the FastAPI server
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from core.lifespan import lifespan
from core.config import get_settings

# Customize route id's
# Helpful for creating sensible names in the client
def custom_generate_unique_id(route: APIRoute):
    return f"{route.name}" # these must be unique

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
    allow_headers=["*"]
)

# Create a simple health check endpoint
@app.get("/", tags=['index'])
def root():
    return {"message": "Welcome to the NGS360 API!"}

# REST routers
# Add each api/feature folder here
api_prefix = "/api/v1"
from api.project.routes import router as project_router
from api.samples.routes import router as samples_router

app.include_router(project_router, prefix=api_prefix)
app.include_router(samples_router, prefix=api_prefix)

if __name__ == '__main__':
    # For debugging purposes
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)