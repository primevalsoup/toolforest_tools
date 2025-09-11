from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

from pydantic import BaseModel, ValidationError

from .registry import ToolRegistry
from .context import RequestContext, set_request_context


class RpcError(Exception):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def _response(result: Dict[str, Any] | None = None, error: Dict[str, str] | None = None) -> Dict[str, Any]:
    if error is not None:
        return {"error": error}
    return {"result": result}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    start = time.time()
    env = os.getenv("ENV", "dev")
    registry = ToolRegistry.instance()

    # Extract optional auth context
    user_jwt = ""
    ctx = event.get("context") or {}
    if isinstance(ctx, dict):
        user_jwt = str(ctx.get("user_jwt") or "")
    set_request_context(RequestContext(user_jwt=user_jwt))

    try:
        action = event.get("action")
        if action == "describe_tools":
            desc = registry.describe()
            manifest = {
                "toolset": registry.toolset_name or "unknown",
                "toolset_version": registry.toolset_version or "0.0.0",
                "manifest_version": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tools": desc,
            }
            return _response(manifest)

        if action == "invoke":
            method = event.get("method")
            if not isinstance(method, str):
                raise RpcError("BadRequest", "'method' must be a string")
            spec = registry.get_tool(method)
            raw_params = event.get("params", {})
            if not isinstance(raw_params, dict):
                raise RpcError("BadRequest", "'params' must be an object")
            try:
                params_model: BaseModel = spec.params_model(**raw_params)
            except ValidationError as ve:
                raise RpcError("ValidationError", ve.json())
            result_model: BaseModel = spec.func(params_model)
            if not isinstance(result_model, spec.result_model):
                raise RpcError("InternalError", "Tool returned wrong result type")
            return _response(result_model.model_dump())

        raise RpcError("BadRequest", "Unknown action")

    except RpcError as e:
        return _response(error={"type": e.error_type, "message": e.message})
    except Exception as e:  # noqa: BLE001
        return _response(error={"type": "InternalError", "message": str(e)})
    finally:
        duration_ms = int((time.time() - start) * 1000)
        print(
            json.dumps(
                {
                    "level": "INFO",
                    "env": env,
                    "event": "lambda_request",
                    "duration_ms": duration_ms,
                    "action": event.get("action"),
                    "has_user_jwt": bool(user_jwt),
                }
            )
        )
