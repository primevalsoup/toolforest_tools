#!/usr/bin/env python3
from __future__ import annotations

import os
from typing import Any, Dict, List

# Prefer adapter submodules; fall back to local implementations if unavailable
try:
    from mcp_server_adapter.registry import load_registry as _load_registry  # type: ignore
    from mcp_server_adapter.proxies import load_toolset_proxies as _load_toolset_proxies  # type: ignore
    from mcp_server_adapter.context import set_context_provider  # type: ignore
    HAVE_ADAPTER = True
except Exception:  # noqa: BLE001
    HAVE_ADAPTER = False
    set_context_provider = None  # type: ignore


def _fallback_load_registry(env: str) -> List[Dict[str, Any]]:
    import boto3
    import json

    ssm = boto3.client("ssm")
    path = f"/toolforest/{env}/toolsets/"
    paginator = ssm.get_paginator("get_parameters_by_path")
    entries: List[Dict[str, Any]] = []
    for page in paginator.paginate(Path=path, WithDecryption=True, Recursive=True):
        for param in page.get("Parameters", []):
            try:
                entries.append(json.loads(param["Value"]))
            except Exception:  # noqa: BLE001
                continue
    return entries


def _fallback_load_toolset_proxies(entries: List[Dict[str, Any]]):
    import boto3
    import json

    lambda_client = boto3.client("lambda")

    def build_invoke(arn: str, method: str):
        def _call(**kwargs: Any) -> Any:
            ctx = {}
            jwt = os.getenv("MCP_USER_JWT", "")
            if jwt:
                ctx = {"user_jwt": jwt}
            payload = {"action": "invoke", "method": method, "params": kwargs}
            if ctx:
                payload["context"] = ctx
            resp = lambda_client.invoke(FunctionName=arn, Payload=json.dumps(payload).encode("utf-8"))
            body = resp["Payload"].read().decode("utf-8")
            data = json.loads(body or "{}")
            if "error" in data:
                err = data["error"]
                raise RuntimeError(f"{err.get('type')}: {err.get('message')}")
            return data.get("result")

        return _call

    proxies: Dict[str, Any] = {}
    for entry in entries:
        arn = entry.get("alias_arn") or entry.get("lambda_function_arn")
        name = entry.get("name", "unknown")
        # discover tools
        desc_payload = {"action": "describe_tools"}
        jwt = os.getenv("MCP_USER_JWT", "")
        if jwt:
            desc_payload["context"] = {"user_jwt": jwt}
        m = lambda_client.invoke(FunctionName=arn, Payload=json.dumps(desc_payload).encode("utf-8"))
        import json as _json

        manifest = _json.loads(m["Payload"].read().decode("utf-8") or "{}")
        tools = manifest.get("result", {}).get("tools", [])
        for t in tools:
            method = t.get("name")
            if not method:
                continue
            proxies[f"{name}.{method}"] = build_invoke(arn, method)
    return proxies


def main() -> None:
    env = os.getenv("ENV", "dev")

    # Register context provider to propagate JWT from environment if adapter is present
    if HAVE_ADAPTER and set_context_provider is not None:
        set_context_provider(lambda: {"user_jwt": os.getenv("MCP_USER_JWT", "")})

    if HAVE_ADAPTER:
        entries = _load_registry(env)  # type: ignore
        proxies = _load_toolset_proxies(entries)  # type: ignore
    else:
        entries = _fallback_load_registry(env)
        proxies = _fallback_load_toolset_proxies(entries)

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
    got = w.get("user_jwt") if isinstance(w, dict) else None
    strict = os.getenv("STRICT_JWT", "0").lower() in ("1", "true", "yes", "on")
    if env == "prod" or strict:
        if got != expected:
            raise SystemExit(f"JWT propagation failed: expected {expected}, got {w}")
    else:
        if got != expected:
            print(f"JWT propagation not enforced in {env}: expected {expected}, got {w}")
    print({"user_jwt": got})


if __name__ == "__main__":
    main()
