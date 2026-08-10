# Experiment A — NL2SQL framework selection (local)

Compare the six frameworks on a **laptop Docker** layout (DB + GPU/Ollama + one NL2SQL stack) using a small harness suite. This is the **local** selection experiment (fast iteration; Qwen, not Arctic).

## Scope

| Item | Value |
|------|--------|
| Frameworks | `langchain`, `dbgpt`, `premsql`, `vanna`, `wrenai`, `chat2db` |
| Model | `qwen2.5:7b-instruct` (see `env.local.example`) |
| Database | PostgreSQL **1-db** — Formula 1 tables in `public` via included seed |
| Suite | `smoke_3` (question IDs 847, 850, 854) — extend to `small_10` if desired |
| Harness DSN | `postgresql://olap:olap@127.0.0.1:55432/bird` |
| Package dir | `nl2sql-comparison/` |

Do **not** compare these scores to AWS Arctic runs without labeling the model.

## Prerequisites

- Docker Desktop with GPU support (or CPU Ollama via `docker-compose.gpu.cpu.yml`)
- PowerShell 7+
- Python 3.13 + Playwright:

```powershell
cd nl2sql-comparison\harness
py -3.13 -m pip install -e ".[ui]"
py -3.13 -m playwright install chromium
```

## Reproduce

```powershell
cd nl2sql-comparison
copy env.local.example compose\.env

.\scripts\local\up-db.ps1
.\scripts\local\load_bird_1db.ps1
.\scripts\local\up-gpu.ps1
.\scripts\local\smoke-db.ps1 -Profile 1db
.\scripts\local\smoke-gpu.ps1

# One framework at a time:
.\scripts\local\up-stack.ps1 -Stack langchain -WithUI
.\scripts\local\run-benchmark.ps1 -Stack langchain -Suite smoke_3 -DbProfile 1db

# Stop stack, then repeat for dbgpt, premsql, vanna, wrenai, chat2db
```

Optional UI smoke across drivers:

```powershell
.\scripts\local\smoke-harness-ui.ps1
```

## Config pointers

| Concern | Where |
|---------|--------|
| Env / ports / model | `env.local.example` |
| Compose | `compose/docker-compose.*.yml`, `compose/stacks/*/docker-compose.yml` |
| Seed SQL | `stack/bird/seed/formula_1_seed.sql` (**included**; not full BIRD) |
| Suite definition | `harness/test_suites/minidev/smoke_3.json` (+ gold JSONL) |

## Notes

- Full BIRD Mini-Dev PG dump is **not** required for this experiment.
- Chat2DB may need AI/Ollama seeding before UI scoring (`harness/scripts/seed_chat2db_ai_playwright.py`).
- Wren on 1-db: keep tables in `public` (`--db-profile 1db` / `WREN_TARGET_SCHEMAS` as documented in ops docs).
