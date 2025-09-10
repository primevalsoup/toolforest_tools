from __future__ import annotations

import inspect
import json
from typing import Any, Callable, Dict, List

import boto3
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(wait=wait_exponential(multiplier=0.2, min=0.2, max=2), stop=stop_after_attempt(3))
def _invoke_lambda(function_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    client = boto3.client("lambda")
    resp = client.invoke(FunctionName=function_name, Payload=json.dumps(payload).encode("utf-8"))
    body = resp["Payload"].read().decode("utf-8")
    return json.loads(body or "{}")


def load_toolset_proxies(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    proxies: Dict[str, Any] = {}
    for entry in entries:
        alias_arn = entry.get("alias_arn") or entry.get("lambda_function_arn")
        toolset_name = entry.get("name", "unknown")

        # Describe tools to build dynamic functions
        manifest = _invoke_lambda(alias_arn, {"action": "describe_tools"})
        tools = manifest.get("result", {}).get("tools", [])

        for t in tools:
            method_name = t["name"]
            doc = t.get("doc", "")

            def make_proxy(function_arn: str, method: str) -> Callable[..., Any]:
                def _call(**kwargs: Any) -> Any:
                    resp = _invoke_lambda(function_arn, {"action": "invoke", "method": method, "params": kwargs})
                    if "error" in resp:
                        err = resp["error"]
                        raise RuntimeError(f"{err.get('type')}: {err.get('message')}")
                    return resp.get("result")

                _call.__name__ = method
                _call.__doc__ = doc
                _call.__signature__ = inspect.Signature(
                    parameters=[
                        inspect.Parameter(name=k, kind=inspect.Parameter.KEYWORD_ONLY)
                        for k in t.get("params_schema", {}).get("properties", {}).keys()
                    ],
                    return_annotation=inspect.Signature.empty,
                )
                return _call

            proxies[f"{toolset_name}.{method_name}"] = make_proxy(alias_arn, method_name)

    return proxies
