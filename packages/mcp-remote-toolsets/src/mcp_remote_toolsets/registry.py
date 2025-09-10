from __future__ import annotations

from typing import Any, Dict, List

import boto3


def load_registry(env: str) -> List[Dict[str, Any]]:
    ssm = boto3.client("ssm")
    path = f"/toolforest/{env}/toolsets/"
    paginator = ssm.get_paginator("get_parameters_by_path")

    entries: List[Dict[str, Any]] = []
    for page in paginator.paginate(Path=path, WithDecryption=True, Recursive=True):
        for param in page.get("Parameters", []):
            try:
                value = param["Value"]
                # Values are JSON objects; defer parsing to callers if desired
                import json

                entries.append(json.loads(value))
            except Exception:  # noqa: BLE001
                continue
    return entries
