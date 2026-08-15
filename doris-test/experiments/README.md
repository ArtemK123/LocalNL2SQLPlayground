# Experiment profiles

JSON profiles drive [`scripts/aws/run-benchmark-aws.ps1`](../scripts/aws/run-benchmark-aws.ps1).

| Profile | Intent |
|---------|--------|
| `arctic-vllm-studyparity-doris-diverse10.json` | Dual-DSN gate (N=10) |
| `arctic-vllm-studyparity-doris-full.json` | Dual-DSN full Mini-Dev (N=500) |

Reports: [`arctic-vllm-doris-vs-sqlite-postgres.md`](arctic-vllm-doris-vs-sqlite-postgres.md), [`arctic-vllm-doris-minidev-analysis.md`](arctic-vllm-doris-minidev-analysis.md), [`arctic-vllm-doris-deploy-runtime-metrics.md`](arctic-vllm-doris-deploy-runtime-metrics.md).
