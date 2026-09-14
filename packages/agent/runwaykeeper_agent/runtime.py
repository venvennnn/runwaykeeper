from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models import Workspace

_CTX: ContextVar["ToolRuntime"] = ContextVar("runwaykeeper_tool_runtime")


@dataclass
class ToolRuntime:
    db: Session
    workspace: Workspace
    tool_calls: list[dict] = field(default_factory=list)

    def log(self, name: str, arguments: dict, result: Any) -> Any:
        self.tool_calls.append({"tool": name, "arguments": arguments, "result_keys": list(result) if isinstance(result, dict) else []})
        return result


def get_runtime() -> ToolRuntime:
    return _CTX.get()


def set_runtime(runtime: ToolRuntime):
    return _CTX.set(runtime)


def reset_runtime(token) -> None:
    _CTX.reset(token)
