# Experiment C — LangChain + Arctic on AWS (PostgreSQL)

Final accuracy/latency evaluation of the **chosen** stack: **LangChain HTTP API** + **Snowflake Arctic-Text2SQL-R1-7B** on **vLLM**, scored on **BIRD Mini-Dev (N=500)** with **PostgreSQL** evaluation (study-parity schema linking).

## Scope

| Item | Value |
|------|--------|
| Framework | `langchain` only (`mode=api`) |
| Model / backend | `Snowflake/Arctic-Text2SQL-R1-7B` / **vLLM** |
| Schema linking | BM25(q+evidence) **top_k=8** + FK neighbors; CREATE TABLE from `dev_tables.json` |
| Decoding | One-pass SQL-fence prefill + stop; harness timeout **10 s**; `workers=2` |
| Prompt dialect | `postgresql` (`arctic_sql_dialect`) |
| Eval | Postgres via tunnel `:55433`; `ex_mode=bird` |
| Suite | `full` (500 Mini-Dev questions) |
| Profile | `experiments/profiles/arctic-vllm-studyparity-postgres-full.json` |
| Reference results | `results/aws_20260809_studyparity_postgres/` |

Headline reference (committed): Strict EX **0.420** (210/500) on Postgres study-parity; see `summary.md`.  
Related SQLite study-parity (same generation knobs): `results/aws_20260809_studyparity_full/` Strict EX **0.536**.

## Prerequisites

- Same AWS cluster bootstrap as Experiment B (Terraform, `ensure-cluster`, BIRD on DB via S3).
- GPU deployed with **vLLM** (not only Ollama):

```powershell
.\scripts\aws\deploy-gpu-vllm-from-s3.ps1
```

- Laptop: Python harness + Playwright; Mini-Dev assets per [DATASETS.md](../DATASETS.md).
- Fill `env.aws.example` values on hosts (`LLM_BACKEND=vllm`, `VLLM_MODEL=Snowflake/Arctic-Text2SQL-R1-7B`, schema BM25 knobs).

## Reproduce

```powershell
cd nl2sql-comparison
aws sts get-caller-identity
.\scripts\aws\ensure-cluster.ps1

# Gate (N=10) before full 500
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-studyparity-postgres-diverse10.json `
  -SkipPublish

# Full Mini-Dev on PostgreSQL
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-studyparity-postgres-full.json `
  -SkipPublish
```

Optional SQLite Gen-EX parity (edit `sqlite_databases_dir` in profile to your Mini-Dev path):

```powershell
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-onepass-10s-full.json `
  -SkipPublish
```

## Config pointers

| Concern | Where |
|---------|--------|
| Profile | `experiments/profiles/arctic-vllm-studyparity-postgres-full.json` |
| Prompt + BM25 code | `stacks/langchain/langchain_api/app/agent.py`, `schema_bm25.py` |
| Compose env | `compose/stacks/langchain/docker-compose.yml`, `env.aws.example` |
| vLLM compose | `compose/docker-compose.gpu.vllm.yml` |
| Reference results | `results/aws_20260809_studyparity_postgres/` (and related gate/full folders) |
| Knobs summary | [docs/IMPLEMENTATION_DETAILS.md](../docs/IMPLEMENTATION_DETAILS.md) |

## Interpretation note

Prefer **Strict EX** (timeouts and `eval_error` count as failures). Postgres **scored** EX (mean over rows that completed eval) can look higher than Strict EX because dialect/`eval_error` rows are excluded from the scored mean.
