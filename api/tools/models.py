from typing import List, Optional, Any, Dict
from pydantic import BaseModel, model_validator
from enum import Enum


class InputType(str, Enum):
    ENUM = "Enum"
    STRING = "String"
    INTEGER = "Integer"
    BOOLEAN = "Boolean"


class ToolConfigInput(BaseModel):
    name: str
    desc: str
    type: InputType
    required: bool = False
    default: Optional[Any] = None
    options: Optional[List[str]] = None

    @model_validator(mode='after')
    def validate_enum_has_options(self):
        if self.type == InputType.ENUM and not self.options:
            raise ValueError("Input type 'Enum' must have options defined")
        return self


class ToolConfigTag(BaseModel):
    name: str


class AwsBatchEnvironment(BaseModel):
    name: str
    value: str


class AwsBatchConfig(BaseModel):
    job_name: str
    job_definition: str
    job_queue: str
    command: str
    environment: Optional[List[AwsBatchEnvironment]] = None


class ToolConfig(BaseModel):
    version: int
    tool_id: str
    tool_name: str
    tool_description: str
    inputs: List[ToolConfigInput]
    help: str
    tags: List[ToolConfigTag]
    aws_batch: Optional[AwsBatchConfig] = None


class ToolSubmitBody(BaseModel):
    tool_id: str
    run_barcode: str
    inputs: Dict[str, Any]
