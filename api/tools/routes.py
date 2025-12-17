"""
Routes/endpoints for the Tools API
"""

from fastapi import APIRouter, Depends

from api.tools.models import ToolConfig
from api.tools import services
from core.deps import get_s3_client

router = APIRouter(prefix="/tools", tags=["Tool Endpoints"])


@router.get("/", response_model=list[str], tags=["Tool Endpoints"])
def list_available_tools(
    s3_client=Depends(get_s3_client),
) -> list[str]:
    """
    List all available tool configurations from S3.
    
    Returns a list of tool IDs (config filenames without extensions).
    """
    return services.list_tool_configs(s3_client=s3_client)


@router.get("/{tool_id}", response_model=ToolConfig, tags=["Tool Endpoints"])
def get_tool_config(
    tool_id: str,
    s3_client=Depends(get_s3_client),
) -> ToolConfig:
    """
    Retrieve a specific tool configuration.
    
    Args:
        tool_id: The tool identifier (filename without extension)
    
    Returns:
        Complete tool configuration
    """
    return services.get_tool_config(tool_id=tool_id, s3_client=s3_client)
