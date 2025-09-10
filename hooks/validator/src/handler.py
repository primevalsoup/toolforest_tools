from __future__ import annotations

import json
import os
from typing import Any, Dict

ALLOWED_RUNTIME = {"python3.12"}
MAX_TIMEOUT = 30
MAX_MEMORY = 1024
REQUIRED_TAGS = {"toolset_id", "owner", "env"}
STACK_TAG_GATE_KEY = "toolforest-tools"
STACK_TAG_GATE_VALUE = "1"


def _success() -> Dict[str, Any]:
    return {"status": "SUCCESS", "message": "ok"}


def _failure(msg: str) -> Dict[str, Any]:
    return {"status": "FAILURE", "message": msg}


def handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    # CloudFormation Hook-style event (simplified expectations)
    # Fall back to SUCCESS if format differs; hooks framework will surface issues during registration/testing
    try:
        hook_context = event.get("hookContext", {})
        target_name = hook_context.get("targetName")  # e.g., AWS::Lambda::Function
        stack_tags: Dict[str, str] = hook_context.get("stackTags", {})
        request_data = event.get("requestData", {})
        resource_props: Dict[str, Any] = request_data.get("resourceProperties", {})
        # Only enforce if stack has the gating tag
        if stack_tags.get(STACK_TAG_GATE_KEY) != STACK_TAG_GATE_VALUE:
            return _success()

        if target_name == "AWS::Lambda::Function":
            runtime = resource_props.get("Runtime")
            if runtime not in ALLOWED_RUNTIME:
                return _failure(f"Runtime {runtime} not allowed; must be one of {sorted(ALLOWED_RUNTIME)}")
            timeout = int(resource_props.get("Timeout", 0))
            memory = int(resource_props.get("MemorySize", 0))
            if timeout > MAX_TIMEOUT:
                return _failure(f"Timeout {timeout}s exceeds max {MAX_TIMEOUT}s")
            if memory > MAX_MEMORY:
                return _failure(f"Memory {memory}MB exceeds max {MAX_MEMORY}MB")
            # Tags check (Tags can be list of {Key,Value})
            tags_list = resource_props.get("Tags", []) or []
            present = {t.get("Key"): t.get("Value") for t in tags_list if isinstance(t, dict)}
            missing = [t for t in REQUIRED_TAGS if t not in present]
            if missing:
                return _failure(f"Missing required tags: {missing}")
            return _success()

        if target_name == "AWS::Lambda::Alias":
            alias_name = resource_props.get("Name")
            env = stack_tags.get("env")
            if env and alias_name != env:
                return _failure(f"Alias name {alias_name} must equal env {env}")
            return _success()

        if target_name == "AWS::IAM::Role":
            # Placeholder for IAM validations as needed
            return _success()

        # Unhandled resource types pass
        return _success()

    except Exception as exc:  # noqa: BLE001
        return _failure(f"Unhandled error: {exc}")
