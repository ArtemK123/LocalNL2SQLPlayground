# NL2SQL comparison harness

Browser-driven benchmark harness for `nl2sql-comparison`. Scored runs support **UI** (Playwright) and **API** modes (`run-api` for langchain/dbgpt).

Parent docs: [../EXPERIMENTS.md](../EXPERIMENTS.md) · [../AI_OPERATIONS.md](../AI_OPERATIONS.md) · [../../experiments/](../../experiments/)

## Requirements

- Python **3.10+** (e.g. `py -3.13` on Windows if default Python is 3.8)
- Docker stacks from `nl2sql-comparison` (DB, GPU, one NL2SQL stack)
- **Local model:** `compose/.env` from `env.local.example` → **`qwen2.5:7b-instruct`** (Arctic is AWS-only)
- **1-db (local):** `load_bird_1db.ps1` — no `datasets/` clone required for `smoke_3`
- **Full BIRD:** `datasets/minidev/` for `load_bird_dev.ps1` and suites `small_10` … `full`

## Install

```powershell
cd nl2sql-comparison\harness
py -3.13 -m pip install -e ".[ui]"
py -3.13 -m playwright install chromium
```

## Ad-hoc SQL evaluation (one question)

Compare predicted SQL vs gold by `question_id` (same EX / soft_f1 as scored runs):

```powershell
$env:PYTHONPATH = "harness/src"
py -3.13 -m nl2sql_comparison_harness eval-sql --question-id 847 --pred-sql "SELECT ..." `
  --dsn "postgresql://olap:olap@127.0.0.1:55432/bird"
```

## Stage 1 — local `smoke_3`

```powershell
cd nl2sql-comparison
.\scripts\local\up-db.ps1
.\scripts\local\load_bird_1db.ps1
.\scripts\local\smoke-db.ps1 -Profile 1db
.\scripts\local\up-gpu.ps1
.\scripts\local\up-stack.ps1 -Stack langchain -WithUI -Build
.\scripts\local\run-benchmark.ps1 -Stack langchain -Suite smoke_3 -DbProfile 1db
```

`run` always drives the framework UI:

```powershell
py -3.13 -m nl2sql_comparison_harness run `
  --framework langchain `
  --suite smoke_3 `
  --dsn "postgresql://olap:olap@127.0.0.1:55432/bird" `
  --trace
```

Summarize:

```powershell
py -3.13 -m nl2sql_comparison_harness summarize harness\runs\*.jsonl --table
```

### Smoke all frameworks (local)

```powershell
cd nl2sql-comparison
.\scripts\local\smoke-harness-ui.ps1          # Playwright ensure_ready only (~2 min)
.\scripts\local\smoke-harness-run.ps1 -Limit 1 -Timeout 180   # one JSONL row per stack
py -3.13 -m nl2sql_comparison_harness smoke-ui --framework langchain
```

## Test suites

| Suite | Size | Selection |
|-------|------|-----------|
| `smoke_3` | 3 | Fixed formula_1 IDs: **847**, **850**, **854** (requires **1-db** load) |
| `small_10` | 10 | Stratified (deterministic) |
| `medium_25` | 25 | Stratified |
| `big_100` | 100 | Stratified |
| `full` | 500 | All minidev questions |

Regenerate after dataset updates:

```powershell
py -3.13 harness\scripts\build_minidev_suites.py --all
```

## Framework UI URLs

| Framework | URL |
|-----------|-----|
| langchain | http://127.0.0.1:8501 (Chainlit; `up-stack -WithUI`) |
| dbgpt | http://127.0.0.1:5670 |
| premsql | http://127.0.0.1:8010 |
| vanna | http://127.0.0.1:8001 |
| wrenai | http://127.0.0.1:3001 |
| chat2db | http://127.0.0.1:10825 |

## Bootstrap helpers

**Wren** — generate table list before deploy:

```powershell
py -3.13 harness\scripts\wren\generate_target_tables.py --suite smoke_3 --print-export
```

**Chat2DB** — DB connections via compose bootstrap; Custom AI is manual or:

```powershell
py -3.13 harness\scripts\seed_chat2db_ai_playwright.py --headed
.\scripts\local\up-stack.ps1 -Stack chat2db -Bootstrap
```

## MCP debug bridge (optional)

When native selectors break, set:

```powershell
$env:NL2SQL_PLAYWRIGHT_MCP_CMD = "py -3.13 harness\scripts\playwright_mcp_bridge.py"
$env:NL2SQL_PLAYWRIGHT_MCP_EXEC_CMD = "<your MCP executor>"
```

## Metrics

- **EX** — BIRD multiset execution match (primary)
- **soft_f1** — partial overlap
- **latency_ms** — UI submit → SQL visible
- **resources** — `docker stats` peaks (`local_docker` provider)

## Stage 2 — AWS

**Orchestrator (recommended):**

```powershell
cd nl2sql-comparison
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/probe-smoke3.json
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-small10-all.json
```

See [`EXPERIMENTS.md`](../EXPERIMENTS.md) and Cursor skill **run-nl2sql-aws-experiments**.

| Item | Value |
|------|--------|
| Eval DSN | `postgresql://olap:olap@127.0.0.1:55433/bird` (SSH to DB host) |
| UI | SSH forwards to NL2SQL (`write-ssh-config.ps1`) |
| Resources | `--resources none` |
| Results | `results/<run_id>/` (+ copies under `harness/runs/`) |

Manual single-stack: `start-stack.ps1` → port-forward → `nl2sql_comparison_harness run` as in Stage 1 with DSN above.

`AwsResourceProvider` is a stub — use `none` on AWS.
