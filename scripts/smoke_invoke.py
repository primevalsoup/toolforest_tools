#!/usr/bin/env python3
from __future__ import annotations

import os

from mcp_server_adapter import load_registry, load_toolset_proxies
from mcp_server_adapter import set_context_provider


def main() -> None:
    env = os.getenv("ENV", "dev")

    # Register context provider to propagate JWT from environment
    set_context_provider(lambda: {"user_jwt": os.getenv("MCP_USER_JWT", "")})

    entries = load_registry(env)
    proxies = load_toolset_proxies(entries)

    # Basic add test
    add = proxies.get("math.add")
    if not add:
        raise SystemExit("math.add not found in registry")
    result = add(x=2, y=40)
    print(result)

    # JWT propagation test
    os.environ["MCP_USER_JWT"] = os.getenv("MCP_USER_JWT", "test-jwt-abc.def.ghijklmnopqrstuvwxyz1234567890abcd")
    whoami = proxies.get("math.whoami")
    if not whoami:
        raise SystemExit("math.whoami not found in registry")
    w = whoami()
    expected = os.environ["MCP_USER_JWT"]
    if not isinstance(w, dict) or w.get("user_jwt") != expected:
        raise SystemExit(f"JWT propagation failed: expected {expected}, got {w}")
    print({"user_jwt": w.get("user_jwt")})


if __name__ == "__main__":
    main()
