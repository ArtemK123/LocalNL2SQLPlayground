from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Optional

from nl2sql_comparison_harness.resources.base import ResourceSnapshot


def _parse_docker_stats_line(line: str) -> dict[str, float]:
    """Parse one line from docker stats --no-stream --format json."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return {}
    cpu_s = str(row.get("CPUPerc", "0")).rstrip("%")
    mem_s = str(row.get("MemUsage", "0B / 0B")).split("/")[0].strip()
    mem_mb = _mem_to_mb(mem_s)
    try:
        cpu = float(cpu_s)
    except ValueError:
        cpu = 0.0
    return {"cpu_pct": cpu, "mem_mb": mem_mb}


def _mem_to_mb(text: str) -> float:
    text = text.strip().upper()
    m = re.match(r"^([\d.]+)\s*([KMGT]?I?B)$", text)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2)
    factors = {"B": 1e-6, "KB": 1e-3, "KIB": 1e-3, "MB": 1.0, "MIB": 1.0, "GB": 1000.0, "GIB": 1024.0}
    return val * factors.get(unit, 1.0)


def _docker_stats(names: list[str]) -> list[dict[str, float]]:
    if not names:
        return []
    try:
        proc = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *names],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out = []
    for line in proc.stdout.splitlines():
        parsed = _parse_docker_stats_line(line.strip())
        if parsed:
            out.append(parsed)
    return out


def _nvidia_smi_peak() -> tuple[Optional[float], Optional[float]]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None, None
    line = proc.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 2:
        return None, None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None, None


class LocalDockerResourceProvider:
    def __init__(
        self,
        *,
        ollama_container: str = "nl2sql-comparison-ollama-1",
        stack_containers: Optional[list[str]] = None,
        sample_gpu: bool = True,
    ) -> None:
        self.ollama_container = os.environ.get("NL2SQL_OLLAMA_CONTAINER", ollama_container)
        self.stack_containers = stack_containers or []
        self.sample_gpu = sample_gpu
        self._ollama_cpu_peak = 0.0
        self._ollama_mem_peak = 0.0
        self._stack_cpu_peak = 0.0
        self._stack_mem_peak = 0.0
        self._gpu_util_peak: Optional[float] = None
        self._gpu_mem_peak: Optional[float] = None

    def start(self, question_ctx: dict[str, Any]) -> None:
        del question_ctx
        self._sample()

    def _sample(self) -> None:
        ollama_stats = _docker_stats([self.ollama_container]) if self.ollama_container else []
        for s in ollama_stats:
            self._ollama_cpu_peak = max(self._ollama_cpu_peak, s.get("cpu_pct", 0.0))
            self._ollama_mem_peak = max(self._ollama_mem_peak, s.get("mem_mb", 0.0))

        stack_stats = _docker_stats(self.stack_containers) if self.stack_containers else []
        for s in stack_stats:
            self._stack_cpu_peak = max(self._stack_cpu_peak, s.get("cpu_pct", 0.0))
            self._stack_mem_peak = max(self._stack_mem_peak, s.get("mem_mb", 0.0))

        if self.sample_gpu:
            util, mem = _nvidia_smi_peak()
            if util is not None:
                self._gpu_util_peak = max(self._gpu_util_peak or 0.0, util)
            if mem is not None:
                self._gpu_mem_peak = max(self._gpu_mem_peak or 0.0, mem)

    def stop(self) -> ResourceSnapshot:
        self._sample()
        snap: ResourceSnapshot = {
            "provider": "local_docker",
            "ollama_cpu_pct_peak": self._ollama_cpu_peak,
            "ollama_mem_mb_peak": self._ollama_mem_peak,
            "stack_cpu_pct_peak": self._stack_cpu_peak,
            "stack_mem_mb_peak": self._stack_mem_peak,
        }
        if self._gpu_util_peak is not None:
            snap["gpu_util_pct_peak"] = self._gpu_util_peak
        if self._gpu_mem_peak is not None:
            snap["gpu_mem_mb_peak"] = self._gpu_mem_peak
        return snap
