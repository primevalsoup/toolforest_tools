from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Type

from pydantic import BaseModel


@dataclass
class ToolSpec:
    name: str
    doc: str
    params_model: Type[BaseModel]
    result_model: Type[BaseModel]
    func: Callable[..., Any]


class ToolRegistry:
    _instance: "ToolRegistry" | None = None

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self.toolset_name: str | None = None
        self.toolset_version: str | None = None

    @classmethod
    def instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = ToolRegistry()
        return cls._instance

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool '{spec.name}' already registered")
        self._tools[spec.name] = spec

    def describe(self) -> List[Dict[str, Any]]:
        descriptions: List[Dict[str, Any]] = []
        for spec in self._tools.values():
            params_schema = spec.params_model.model_json_schema()
            result_schema = spec.result_model.model_json_schema()
            descriptions.append(
                {
                    "name": spec.name,
                    "doc": spec.doc,
                    "params_schema": params_schema,
                    "result_schema": result_schema,
                }
            )
        return descriptions

    def get_tool(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def list_names(self) -> List[str]:
        return list(self._tools.keys())
