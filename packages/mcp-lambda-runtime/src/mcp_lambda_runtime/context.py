from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RequestContext:
    user_jwt: str = ""


_current_context: ContextVar[RequestContext] = ContextVar("mcp_lambda_request_context", default=RequestContext())


def set_request_context(ctx: RequestContext) -> None:
    _current_context.set(ctx)


def get_request_context() -> RequestContext:
    return _current_context.get()


def get_user_jwt() -> str:
    return _current_context.get().user_jwt
