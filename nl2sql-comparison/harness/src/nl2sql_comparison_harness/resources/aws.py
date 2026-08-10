from __future__ import annotations

from typing import Any

from nl2sql_comparison_harness.resources.base import ResourceSnapshot


class AwsResourceProvider:
    """Stage 2 stub — pull docker stats via SSM or CloudWatch in a future implementation."""

    def __init__(self, *, ec2_instance_id: str = "", cloudwatch_namespace: str = "") -> None:
        self.ec2_instance_id = ec2_instance_id
        self.cloudwatch_namespace = cloudwatch_namespace

    def start(self, question_ctx: dict[str, Any]) -> None:
        del question_ctx

    def stop(self) -> ResourceSnapshot:
        return {
            "provider": "aws_stub",
            "ec2_instance_id": self.ec2_instance_id or None,
            "cloudwatch_namespace": self.cloudwatch_namespace or None,
        }
