#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

ALLOWED_RUNTIME = {"python3.12"}
MAX_TIMEOUT = 30
MAX_MEMORY = 1024
REQUIRED_TAGS = {"toolset_id", "owner", "env"}
GATE_TAG_KEY = "toolforest-tools"
GATE_TAG_VALUE = "1"


def has_gate_tag(template: Dict[str, Any]) -> bool:
    # Stack-level tags are not directly in the template; approximate by checking resource tags on the Function
    resources = template.get("Resources", {})
    for res in resources.values():
        props = res.get("Properties", {})
        tags = props.get("Tags")
        if isinstance(tags, list):
            kv = {t.get("Key"): t.get("Value") for t in tags if isinstance(t, dict)}
            if kv.get(GATE_TAG_KEY) == GATE_TAG_VALUE:
                return True
    return False


def validate_template(path: Path) -> None:
    with path.open("r", encoding="utf-8") as f:
        template = json.load(f)

    if not has_gate_tag(template):
        return

    resources = template.get("Resources", {})
    for name, res in resources.items():
        rtype = res.get("Type")
        props = res.get("Properties", {})
        if rtype == "AWS::Lambda::Function":
            runtime = props.get("Runtime")
            if runtime not in ALLOWED_RUNTIME:
                raise SystemExit(f"{path.name}: Function {name} runtime {runtime} not allowed")
            timeout = int(props.get("Timeout", 0))
            memory = int(props.get("MemorySize", 0))
            if timeout > MAX_TIMEOUT:
                raise SystemExit(f"{path.name}: Function {name} timeout {timeout}s exceeds {MAX_TIMEOUT}s")
            if memory > MAX_MEMORY:
                raise SystemExit(f"{path.name}: Function {name} memory {memory}MB exceeds {MAX_MEMORY}MB")
            tags = props.get("Tags", [])
            present = {t.get("Key"): t.get("Value") for t in tags if isinstance(t, dict)}
            missing = [t for t in REQUIRED_TAGS if t not in present]
            if missing:
                raise SystemExit(f"{path.name}: Function {name} missing required tags: {missing}")
        if rtype == "AWS::Lambda::Alias":
            alias_name = props.get("Name")
            # Find env tag from any function
            env = None
            for r2 in resources.values():
                if r2.get("Type") == "AWS::Lambda::Function":
                    tags = r2.get("Properties", {}).get("Tags", [])
                    present = {t.get("Key"): t.get("Value") for t in tags if isinstance(t, dict)}
                    env = present.get("env")
                    if env:
                        break
            if env and alias_name != env:
                raise SystemExit(f"{path.name}: Alias {name} name {alias_name} must equal env {env}")


def main() -> None:
    env = os.getenv("ENV", "dev")
    out = Path("cdk.out")
    if not out.exists():
        raise SystemExit("cdk.out not found; run synth first")

    # Validate all templates in cdk.out
    for p in out.glob("*.template.json"):
        validate_template(p)

    print("Template validation passed")


if __name__ == "__main__":
    main()
