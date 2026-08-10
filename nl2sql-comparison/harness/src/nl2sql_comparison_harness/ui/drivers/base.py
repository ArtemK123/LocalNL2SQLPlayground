from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class UIAskResult:
    pred_sql: Optional[str]
    latency_ms: int
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FrameworkUIConfig:
    name: str
    default_url: str


FRAMEWORK_URLS: dict[str, FrameworkUIConfig] = {
    "langchain": FrameworkUIConfig("langchain", "http://127.0.0.1:8501"),
    "dbgpt": FrameworkUIConfig("dbgpt", "http://127.0.0.1:5670"),
    "premsql": FrameworkUIConfig("premsql", "http://127.0.0.1:8501"),
    "vanna": FrameworkUIConfig("vanna", "http://127.0.0.1:8001"),
    "wrenai": FrameworkUIConfig("wrenai", "http://127.0.0.1:3001"),
    "chat2db": FrameworkUIConfig("chat2db", "http://127.0.0.1:10825"),
}

UI_FRAMEWORKS = frozenset(FRAMEWORK_URLS.keys())


class UIDriver(Protocol):
    def ensure_ready(self) -> None: ...

    def ask(self, question: str, *, timeout_s: float) -> UIAskResult: ...


def normalize_framework(name: str) -> str:
    key = name.strip().lower()
    if key not in FRAMEWORK_URLS:
        raise ValueError(f"Unknown framework {name!r}. Choose: {', '.join(sorted(UI_FRAMEWORKS))}")
    return key
