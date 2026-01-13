"""
Models for the Manifest API
"""
from pydantic import BaseModel, Field


class ManifestUploadResponse(BaseModel):
    """Response model for manifest file upload"""

    status: str = Field(..., description="Status of the upload operation")
    message: str = Field(..., description="Human-readable message about the upload")
    path: str = Field(..., description="Full S3 path where the file was uploaded")
    filename: str = Field(..., description="Name of the uploaded file")


class ManifestValidationResponse(BaseModel):
    """Response model for manifest validation"""

    valid: bool = Field(..., description="Whether the manifest is valid")
    message: dict[str, str] = Field(
        default_factory=dict,
        description="Informational messages about the validation"
    )
    error: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Validation errors grouped by category"
    )
    warning: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Validation warnings grouped by category"
    )
