# Experiment results

Each run creates `results/<run_id>/`:

| Path | Git |
|------|-----|
| `manifest.json` | **Commit** |
| `summary.md` | **Commit** |
| `jsonl/*.jsonl` | Ignored |
| `traces/` | Ignored |

Runs are produced by [`scripts/aws/run-benchmark-aws.ps1`](../scripts/aws/run-benchmark-aws.ps1).

See [`EXPERIMENTS.md`](../EXPERIMENTS.md).
