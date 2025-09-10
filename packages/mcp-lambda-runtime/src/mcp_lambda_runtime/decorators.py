from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, Optional, Type, get_type_hints

from pydantic import BaseModel

from .registry import ToolRegistry, ToolSpec


def tool(func: Optional[Callable[..., Any]] = None, *, name: Optional[str] = None) -> Callable[..., Any]:
    """
    Decorator to register a tool function with typed params/result using Pydantic models.

    The function must have the signature: (params: BaseModel) -> BaseModel
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        registry = ToolRegistry.instance()
        tool_name = name or f.__name__

        # Resolve annotations to actual types (handles postponed annotations)
        hints = get_type_hints(f, globalns=f.__globals__, localns=None)
        params_model = hints.get("params")
        result_model = hints.get("return")

        if not (isinstance(params_model, type) and issubclass(params_model, BaseModel)):
            raise TypeError(f"@tool '{tool_name}' must annotate 'params' with a Pydantic BaseModel")
        if not (isinstance(result_model, type) and issubclass(result_model, BaseModel)):
            raise TypeError(f"@tool '{tool_name}' must annotate return type with a Pydantic BaseModel")

        spec = ToolSpec(
            name=tool_name,
            doc=(f.__doc__ or "").strip(),
            params_model=params_model,  # type: ignore[arg-type]
            result_model=result_model,  # type: ignore[arg-type]
            func=f,
        )
        registry.register(spec)

        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return f(*args, **kwargs)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
