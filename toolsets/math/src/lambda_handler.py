from __future__ import annotations

from pydantic import BaseModel, Field

from mcp_lambda_runtime import handler as runtime_handler
from mcp_lambda_runtime import tool, ToolRegistry


class AddParams(BaseModel):
    x: float = Field(..., description="First addend")
    y: float = Field(..., description="Second addend")


class AddResult(BaseModel):
    value: float = Field(..., description="Sum")


@tool
def add(params: AddParams) -> AddResult:
    """Add two numbers."""
    return AddResult(value=params.x + params.y)


# Initialize registry metadata
ToolRegistry.instance().toolset_name = "math"
ToolRegistry.instance().toolset_version = "0.1.0"


def handler(event, context):  # AWS entrypoint
    return runtime_handler(event, context)
