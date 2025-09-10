#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os

from scripts.mcp_server import build_server


async def main() -> None:
    env = os.getenv("ENV", "dev")
    app = build_server(env)
    tools = await app.list_tools()  # type: ignore[func-returns-value]
    names = [t.name for t in tools]
    print({"tools": names})
    result = await app.call_tool("add", {"x": 3, "y": 4})  # type: ignore[func-returns-value]
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
