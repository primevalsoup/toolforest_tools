#!/usr/bin/env python3
from __future__ import annotations

import os

from mcp_remote_toolsets import load_registry, load_toolset_proxies


def main() -> None:
    env = os.getenv("ENV", "dev")
    entries = load_registry(env)
    proxies = load_toolset_proxies(entries)
    add = proxies.get("math.add")
    if not add:
        raise SystemExit("math.add not found in registry")
    result = add(x=2, y=40)
    print(result)


if __name__ == "__main__":
    main()
