#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from mcp_remote_toolsets import load_registry, load_toolset_proxies


def build_server(env: str) -> FastMCP:
    app = FastMCP()

    entries = load_registry(env)
    proxies = load_toolset_proxies(entries)

    # Register each proxy function as a tool in MCP
    for fq_name, fn in proxies.items():
        # Expose tool name without toolset prefix for simplicity
        name = fq_name.split(".", 1)[-1]
        app.add_tool(fn, name=name, description=f"Lambda-backed tool {fq_name}")

    return app


async def main() -> None:
    env = os.getenv("ENV", "dev")
    app = build_server(env)

    # Run over stdio by default for local testing
    await app.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(main())
