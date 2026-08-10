# AWS NL2SQL harness experiments

Human runbook and **agent contract** for repeatable benchmarks on the 3-role AWS cluster (DB + GPU + NL2SQL). Playwright runs on your **Windows laptop**; stacks and Ollama run on EC2.

| Doc | Role |
|-----|------|
| **This file** | Experiment workflow, parameters, results layout |
| [`AI_OPERATIONS.md`](AI_OPERATIONS.md) | Cluster bootstrap, deploy, smokes |
| [`harness/README.md`](harness/README.md) | Harness CLI reference |
| [`../experiments/`](../experiments/) | Final public runbooks A / B / C |

---

## Quick start

1. `cd nl2sql-comparison` → `aws sts get-caller-identity` → `.\scripts\aws\ensure-cluster.ps1`.
2. Install harness once: `py -3.13 -m pip install -e "harness/[ui]"` + `playwright install chromium`.
3. Prefer a **profile** under `experiments/profiles/` or explicit `-Stacks` / `-Suite` / `-Model`.
4. Run `.\scripts\aws\run-benchmark-aws.ps1` (probe first if suite size is unknown).
5. Commit only `results/<run_id>/manifest.json` and `summary.md` (raw JSONL/traces are gitignored). Sanitize account IDs / private IPs / absolute personal paths before publishing.

**Do not** compare local Qwen runs with AWS Arctic (or other models) without labeling `model` in `manifest.json`.

---

## Architecture

```mermaid
sequenceDiagram
  participant Laptop as Laptop_harness
  participant Bastion as Bastion_SSH
  participant NL2SQL as NL2SQL_EC2
  participant GPU as GPU_Ollama
  participant DB as DB_BIRD

  Laptop->>Bastion: SSH -L UI ports to NL2SQL
  Laptop->>Bastion: SSH -L 55433 to DB
  Laptop->>NL2SQL: start-stack via SSM
  NL2SQL->>GPU: OLLAMA_HOST
  NL2SQL->>DB: BIRD_PG_HOST
  Laptop->>Laptop: Playwright UI (headless default)
  Laptop->>DB: EX eval DSN 127.0.0.1:55433
  Laptop->>Laptop: results/run_id/
```

| Component | Where |
|-----------|--------|
| BIRD PostgreSQL | DB EC2 — **75 tables in `public`** (full load) |
| Ollama + model | GPU EC2 — **Arctic** default; **Qwen** for Chat2DB after `set-gpu-model.ps1 -ModelProfile general` |
| NL2SQL stack | NL2SQL EC2 — **one framework at a time** |
| Harness + Playwright | Laptop |
| EX scoring DSN | `postgresql://olap:olap@127.0.0.1:55433/bird` (SSH to DB host) |

---

## Prerequisites (once per session)

```powershell
aws login   # or aws sso login
aws sts get-caller-identity

cd nl2sql-comparison
.\scripts\aws\ensure-cluster.ps1
.\scripts\aws\write-ssh-config.ps1   # needs aws/credentials/test-pair.pem

cd harness
py -3.13 -m pip install -e ".[ui]"
py -3.13 -m playwright install chromium
```

| Check | Command / note |
|-------|----------------|
| GPU model | `deploy-gpu-from-s3.ps1` if GPU was recreated; verify with `get-gpu-active-model.ps1` or `curl $OLLAMA_HOST/api/tags` |
| Chat2DB model | Run `set-gpu-model.ps1 -ModelProfile general` before chat2db stack/benchmark |
| BIRD on DB | `deploy-db-from-s3.ps1 -SkipUpload` only if DB recreated |
| Package on S3 | Use **`-SkipPublish`** on experiments unless `stacks/`, `compose/`, or `scripts/aws/ssm-*.sh` changed |
| SSH | Two tunnel processes: NL2SQL UI ports + DB `:5432` → laptop `55433` (started by `run-benchmark-aws.ps1`) |

---

## Main entrypoint

```powershell
cd nl2sql-comparison

# Latency probe → auto-pick small_10 vs medium_25
.\scripts\aws\run-benchmark-aws.ps1 -ProbeOnly -SkipPublish

# Full run from profile (recommended for repeats)
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-small10-all.json

# Subset: two stacks, smoke suite, custom model label in manifest
.\scripts\aws\run-benchmark-aws.ps1 -Stacks langchain,dbgpt -Suite smoke_3 -Model "a-kore/Arctic-Text2SQL-R1-7B" -SkipPublish

# Exclude a framework
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-small10-all.json -ExcludeStacks chat2db
```

### Parameters (CLI overrides profile)

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `-Profile` | — | JSON under `experiments/profiles/` |
| `-Stacks` | all six (ordered) | Subset, e.g. `langchain,dbgpt` |
| `-ExcludeStacks` | — | Remove from profile/default list |
| `-Suite` | `small_10` (or profile) | `smoke_3`, `small_10`, `medium_25`, `big_100`, `full`, `minidev_diverse_10`, `formula_1_smoke_10` |
| `-AdaptiveSuite` | off | Run `smoke_3` probe on langchain; if avg latency > 60s → `small_10`, else `medium_25` |
| `-ProbeOnly` | off | Probe only; no full pass |
| `-Model` / `-FallbackModel` | Arctic | SQL-stack default in manifest; **chat2db** uses Qwen via `models/stack-models.json` |
| `-SkipModelCheck` | off | Skip GPU active-model verification (advanced; not recommended) |
| `-Timeout` | `900` (or profile `timeout_sec`) | Per-question seconds (Arctic UI often needs 300–900s; API SLA profiles may use `10`) |
| `-Mode` | `ui` (or profile `mode`) | `ui` = Playwright `run`; `api` = `run-api` (langchain/dbgpt only; skips Chainlit) |
| `-Workers` | `1` (or profile `workers`) | Concurrent API clients when `-Mode api` |
| `-Headed` / `-NoHeaded` | headless | Headless by default; `-Headed` or profile `"headed": true` for visible browser (debug; ignored for `mode=api`) |
| `-SkipPublish` | off | Skip `publish-package-to-s3.ps1` |
| `-SkipPreflight` | off | Skip `ensure-cluster.ps1` |
| `-KeepTunnels` | off | Leave SSH forwards running after script |
| `-DryRun` | off | Print plan only |
| `-RunId` | `aws_yyyyMMdd_HHmmss` | Results folder name |

### Per-stack automation

| Stack | Extra step |
|-------|------------|
| **langchain** | UI mode: SSM `ssm-start-langchain-ui.sh` (Chainlit on `:8501`). API mode (`mode=api`): skip Chainlit; harness hits `:8011/v1/chat` |
| **wrenai** | `generate_target_tables.py --db-profile full --scope minidev` + `WREN_TARGET_SCHEMAS` (11 minidev schemas) on deploy |
| **chat2db** | Custom AI seed (add `-Headed` for visible browser); GPU Ollama URL; GPU must have **Qwen** loaded (`set-gpu-model.ps1 -ModelProfile general`) |

**Stack order (default):** langchain → dbgpt → premsql → vanna → wrenai → chat2db.

### Port forwards (automatic)

| Local | Remote (on NL2SQL or DB host) |
|-------|--------------------------------|
| 8501, 5670, 8010, 8001, 3001, 10825 | Same UI ports on NL2SQL `127.0.0.1` |
| **55433** | DB Postgres `5432` |

---

## Suite sizing

| Suite | Questions | Typical use |
|-------|-----------|-------------|
| `smoke_3` | 3 | Pipeline / latency probe |
| `small_10` | 10 | **Default with Arctic** (~5 min/query on g6.xlarge) |
| `medium_25` | 25 | Only if probe avg UI latency ≤ 60s |
| `big_100` / `full` | 100 / 500 | Long overnight runs |

**Wall time (rough):** `small_10` × 6 stacks ≈ 5–8 h; `medium_25` × 6 ≈ 12–18 h.

---

## Experiment profiles

Profiles live in [`experiments/profiles/`](experiments/profiles/). Copy and edit for new model/suite/stack combinations.

```json
{
  "name": "arctic-small10-all",
  "description": "Arctic for SQL stacks; Chat2DB uses Qwen (manual GPU switch before chat2db segment)",
  "model": "a-kore/Arctic-Text2SQL-R1-7B",
  "stack_models": { "chat2db": "qwen2.5:7b-instruct" },
  "suite": "small_10",
  "stacks": ["langchain", "dbgpt", "premsql", "vanna", "wrenai", "chat2db"],
  "timeout_sec": 900,
  "skip_publish": true,
  "adaptive_suite": false
}
```

| Profile file | Intent |
|--------------|--------|
| `probe-smoke3.json` | Probe only |
| `arctic-small10-all.json` | Experiment B — six-framework AWS selection |
| `arctic-vllm-studyparity-postgres-*.json` | Experiment C — Postgres study-parity |
| `arctic-vllm-onepass-10s-*.json` | Experiment C optional — SQLite Gen-EX |

**Changing LLM on GPU:** use `set-gpu-model.ps1 -ModelProfile sql|general` (lazy-pulls secondary model). Deploy with `deploy-gpu-from-s3.ps1 -ActiveModel <tag>` only when resetting the GPU host. Orchestrator **fails** if GPU active model ≠ stack expectation unless `-SkipModelCheck`.

**Mixed-model runs:** run SQL stacks (Arctic) and Chat2DB (Qwen) in separate invocations with a manual switch between them.

---

## Results layout

```
nl2sql-comparison/results/
  <run_id>/
    manifest.json      # commit
    summary.md         # commit (harness summarize output)
    jsonl/             # gitignored
    traces/            # gitignored
```

**Git:** commit `manifest.json` + `summary.md` only. Raw JSONL also appears under `harness/runs/` (already gitignored).

### `manifest.json` (minimum fields)

- `run_id`, `model`, `fallback_model`, `models` (per-framework map), `gpu_active_model_at_start`
- `gpu_instance_type`, `suite`, `questions_per_stack`
- `frameworks[]` with `{ name, model, suite }` per stack run
- `started_at`, `finished_at`, `dsn_eval`
- `jsonl_paths_local[]`, `cluster` (account, region, IPs)

---

## Manual fallback (single stack)

If the orchestrator fails mid-run, run steps from [`harness/README.md`](harness/README.md) Stage 2:

1. `.\scripts\aws\start-stack.ps1 -Stack <name> -SkipPublish`
2. LangChain: `.\scripts\aws\invoke-ssm.ps1` + `ssm-start-langchain-ui.sh`
3. SSH forwards (see `write-ssh-config.ps1` output)
4. `py -3.13 -m nl2sql_comparison_harness run --framework <name> --suite <suite> --dsn ... --resources none --trace` (add `--headed` only for UI debug)

---

## After experiments

1. `.\scripts\aws\stop-system.ps1` when idle (saves EC2 cost).
2. Keep committed `results/<run_id>/manifest.json` + `summary.md` free of real account IDs, private IPs, and personal absolute paths.

---

## Troubleshooting

| Symptom | Action |
|---------|--------|
| SSH tunnel dies | `write-ssh-config.ps1 -Force`; re-run; check bastion / PEM |
| `ensure-cluster` fails | `terraform apply` in `terraform/compute/`; redeploy db/gpu |
| No SQL in JSONL | Check trace under `results/<run_id>/traces/`; retry with `-Headed` |
| Chat2DB empty SQL | GPU on Qwen? `set-gpu-model.ps1 -ModelProfile general`; re-seed with GPU Ollama URL |
| GPU model mismatch | Orchestrator error — run `set-gpu-model.ps1` with suggested profile |
| Wren timeout | Long startup; increase `-Timeout`; confirm `WREN_TARGET_TABLES` |
| Wrong EX / schema | AWS BIRD uses **`public` only** — gold SQL needs no `search_path` patch |
