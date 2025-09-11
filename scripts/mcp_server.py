#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from mcp_remote_toolsets import load_registry, load_toolset_proxies
from mcp_remote_toolsets.proxies import set_context_provider


def get_context() -> Dict[str, Any]:
    # Placeholder: integrate with Anthropic MCP session context to fetch current user's JWT
    # For now, read from env if set; otherwise empty
    jwt = os.getenv("MCP_USER_JWT", "")
    return {"user_jwt": jwt}


def build_server(env: str) -> FastMCP:
    app = FastMCP()

    # Register context provider so all tool invokes include user_jwt transparently
    set_context_provider(get_context)

    entries = load_registry(env)
    proxies = load_toolset_proxies(entries)

    for fq_name, fn in proxies.items():
        name = fq_name.split(".", 1)[-1]
        app.add_tool(fn, name=name, description=f"Lambda-backed tool {fq_name}")

    return app


async def main() -> None:
    env = os.getenv("ENV", "dev")
    app = build_server(env)
    await app.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
