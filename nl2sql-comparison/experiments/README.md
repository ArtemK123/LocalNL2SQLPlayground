# Experiment profiles

JSON profiles drive [`scripts/aws/run-benchmark-aws.ps1`](../scripts/aws/run-benchmark-aws.ps1). CLI flags override profile fields.

**Final public runbooks (A/B/C):** see [`../../experiments/`](../../experiments/) at the repository root.

## Profiles shipped for A/B/C

| Profile file | Experiment | Intent |
|--------------|------------|--------|
| `probe-smoke3.json` | B | Latency probe only |
| `arctic-small10-all.json` | B | Six-framework AWS selection suite |
| `arctic-vllm-studyparity-postgres-diverse10.json` | C | Postgres study-parity gate (N=10) |
| `arctic-vllm-studyparity-postgres-full.json` | C | Postgres study-parity full Mini-Dev (N=500) |
| `arctic-vllm-onepass-10s-diverse10.json` | C (optional) | SQLite Gen-EX gate |
| `arctic-vllm-onepass-10s-full.json` | C (optional) | SQLite Gen-EX full Mini-Dev |
| `_template.json` / `custom-model-template.json` | — | Copy to create custom profiles |

## Usage

```powershell
cd nl2sql-comparison
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-small10-all.json
```

Study-parity schema on Postgres eval:

```powershell
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-vllm-studyparity-postgres-diverse10.json
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-vllm-studyparity-postgres-full.json
```

## Create a new profile

1. Copy `profiles/_template.json` to `profiles/<your-name>.json`.
2. Set `model`, `suite`, `stacks`, `timeout_sec`.
3. Set `skip_publish: true` when S3 package is already current.
4. Document the run in `results/<run_id>/manifest.json` (auto-generated).

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Profile id (informational) |
| `description` | string | Human note |
| `model` | string | Ollama tag on GPU + manifest |
| `fallback_model` | string | Optional; defaults to `model` |
| `suite` | string | Harness suite name |
| `stacks` | string[] | Framework order subset |
| `mode` | string | `ui` (Playwright, default) or `api` (`run-api`; langchain/dbgpt only) |
| `workers` | number | Concurrent API workers when `mode=api` (default `1`) |
| `timeout_sec` | number | Per-question timeout |
| `headed` | bool | Optional; default headless. Set `true` for visible Playwright (debug; ignored for `mode=api`) |
| `skip_publish` | bool | Skip S3 package upload |
| `adaptive_suite` | bool | Probe then pick small_10 vs medium_25 |
| `probe_only` | bool | Run probe only |
| `llm_backend` | string | e.g. `vllm` |
| `eval_engine` | string | `postgres` (default) or `sqlite` |
| `ex_mode` | string | e.g. `bird` set-equality |
| `arctic_sql_dialect` | string | Prompt dialect override (`postgresql` / sqlite default) |
| `sqlite_databases_dir` | string | Path to BIRD minidev `dev_databases` when `eval_engine=sqlite` |

For `mode=api`, Chainlit is not started (HTTP API on `:8011` / `:8012`).

See [`EXPERIMENTS.md`](../EXPERIMENTS.md) for full workflow.
