from __future__ import annotations

from typing import Any, Optional, Protocol, TypedDict


class ResourceSnapshot(TypedDict, total=False):
    provider: str
    ollama_cpu_pct_peak: float
    ollama_mem_mb_peak: float
    stack_cpu_pct_peak: float
    stack_mem_mb_peak: float
    gpu_util_pct_peak: float
    gpu_mem_mb_peak: float
    ec2_instance_id: str
    cloudwatch_namespace: str


class ResourceProvider(Protocol):
    def start(self, question_ctx: dict[str, Any]) -> None: ...

    def stop(self) -> ResourceSnapshot: ...


class NullResourceProvider:
    """No-op provider for runs without resource sampling."""

    def start(self, question_ctx: dict[str, Any]) -> None:
        del question_ctx

    def stop(self) -> ResourceSnapshot:
        return {"provider": "null"}
