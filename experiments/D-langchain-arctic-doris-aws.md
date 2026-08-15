# Experiment D — LangChain + Arctic on AWS (Apache Doris)

Final accuracy/latency evaluation of the **chosen** stack on **Apache Doris**: **LangChain HTTP API** + **Snowflake Arctic-Text2SQL-R1-7B** on **vLLM**, scored on **BIRD Mini-Dev (N=500)** with **cross-engine dual-DSN** (gold on PostgreSQL, predicted SQL on Doris).

Runnable package: [`doris-test/`](../doris-test/). SQLite / Postgres baselines are Experiment C in [`nl2sql-comparison/`](../nl2sql-comparison/).

## Scope

| Item | Value |
|------|--------|
| Framework | `langchain` only (`mode=api`) |
| Model / backend | `Snowflake/Arctic-Text2SQL-R1-7B` / **vLLM** |
| Schema linking | BM25(q+evidence) **top_k=8** + FK; CREATE TABLE from `dev_tables.json` (`SCHEMA_SOURCE=bird_tables`) |
| Decoding | One-pass SQL-fence prefill + stop; harness timeout **10 s**; `workers=2`; `SQL_EXEC_MODE=skip` |
| Prompt dialect | `mysql` (`ARCTIC_SQL_DIALECT`) + universal SQLite→MySQL compiler (no per-question patches) |
| Eval | **dual_dsn**: gold Postgres tunnel `:55433`, pred Doris MySQL `:9031`; `ex_mode=bird` |
| Ingest | CDC from Postgres OLTP (Debezium/Kafka/routine load) — **not** bulk CSV |
| Suite | `full` (500 Mini-Dev questions) |
| Profile | `doris-test/experiments/profiles/arctic-vllm-studyparity-doris-full.json` |
| Reference results | `doris-test/results/doris_20260815_113514/` |

Headline reference (committed): overall EX **0.42** (210/500); EX among `dual_ok` **0.468** (210/449).  
Same-engine baselines (Experiment C knobs): SQLite Strict **0.536**, Postgres Strict **0.420**.

## Methodology reports

| Doc | Contents |
|-----|----------|
| [`doris-test/experiments/arctic-vllm-doris-vs-sqlite-postgres.md`](../doris-test/experiments/arctic-vllm-doris-vs-sqlite-postgres.md) | Methodology, three-way EX tables, systematic error analysis |
| [`doris-test/experiments/arctic-vllm-doris-minidev-analysis.md`](../doris-test/experiments/arctic-vllm-doris-minidev-analysis.md) | Run index / changelog (incl. pre-compiler ablation 0.36) |
| [`doris-test/experiments/arctic-vllm-doris-deploy-runtime-metrics.md`](../doris-test/experiments/arctic-vllm-doris-deploy-runtime-metrics.md) | Four-role deploy / VRAM / start-from-stopped |

Read **overall EX** next to SQLite/Postgres **Strict EX**. Do not compare Doris `dual_ok` EX to Postgres **scored** EX.

## Prerequisites

- AWS account + Terraform (`doris-test/terraform/*/terraform.tfvars.example` → `terraform.tfvars`; **never commit tfvars or PEMs**).
- BIRD Mini-Dev PostgreSQL dump on the laptop — see [DATASETS.md](../DATASETS.md).
- GPU with **vLLM** (deploy after analytics ODS is healthy):

```powershell
cd doris-test
.\scripts\aws\deploy-gpu-vllm-from-s3.ps1
```

- Laptop: Python harness; Mini-Dev assets per DATASETS.md.
- Fill `env.aws.example` on hosts (`LLM_BACKEND=vllm`, `VLLM_MODEL=Snowflake/Arctic-Text2SQL-R1-7B`, `ARCTIC_SQL_DIALECT=mysql`, `SCHEMA_SOURCE=bird_tables`, `SQL_EXEC_MODE=skip`, `DB_URI` MySQL to Doris FE `:9030`).

## Reproduce

```powershell
cd doris-test
aws sts get-caller-identity
.\scripts\aws\ensure-cluster.ps1
.\scripts\aws\deploy-db-from-s3.ps1
.\scripts\aws\deploy-analytics-from-s3.ps1    # CDC snapshot; wait until ODS healthy
.\scripts\aws\deploy-gpu-vllm-from-s3.ps1     # after ODS healthy
.\scripts\aws\deploy-nl2sql-from-s3.ps1
.\scripts\aws\write-ssh-config.ps1
.\scripts\aws\preflight-eval-health.ps1

# Gate (N=10) before full 500
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-studyparity-doris-diverse10.json `
  -SkipPublish

# Full Mini-Dev on Doris (gold=Postgres, pred=Doris)
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-studyparity-doris-full.json `
  -SkipPublish
```

Scoring must run on the **laptop** (tunnels) or analytics host. Gold Postgres is unreachable from nl2sql under the default security group.

Equivalent harness invocation:

```powershell
cd doris-test\harness
py -3 -m pip install -e .
doris-test-harness run-api --suite full `
  --eval-mode dual_dsn `
  --ex-mode bird `
  --gold-dsn "postgresql://olap:olap@127.0.0.1:55433/bird" `
  --pred-dsn "mysql://root@127.0.0.1:9031/bird_minidev_olap" `
  --api-url http://127.0.0.1:8011/v1/chat `
  --workers 2 --timeout 10
```

## Local Compose (optional smoke)

Local default is **Qwen**, not Arctic. CDC is still Postgres→Kafka→Doris (not CSV).

```powershell
cd doris-test
Copy-Item env.local.example compose\.env
.\scripts\local\up-db.ps1
.\scripts\local\load_bird_dev.ps1
.\scripts\local\generate-and-up-analytics.ps1
# wait until ODS/routine loads are healthy, then:
.\scripts\local\up-gpu.ps1
.\scripts\local\up-stack-langchain.ps1
.\scripts\local\smoke-cluster.ps1
```

## Config pointers

| Concern | Where |
|---------|--------|
| Profiles | `doris-test/experiments/profiles/arctic-vllm-studyparity-doris-full.json` (and `…-diverse10.json`) |
| Prompt + compiler | `stacks/langchain/langchain_api/app/agent.py`, `dialect.py`, `sql_guard.py` |
| Compose env | `compose/stacks/langchain/docker-compose.yml`, `env.aws.example` |
| CDC ingest | `stack/connectors/bird-postgres-source.json`, `stack/doris/10_ods_tables.sql`, `20_routine_loads.sql` |
| vLLM compose | `compose/docker-compose.gpu.vllm.yml` |
| Reference results | `results/doris_20260815_113514/` |
| Knobs summary | [docs/IMPLEMENTATION_DETAILS.md](../docs/IMPLEMENTATION_DETAILS.md) |

## Interpretation note

Prefer **overall EX** (API / gold / pred failures count as EX=false). **EX among `dual_ok`** is the cross-engine rate when both engines returned a result set. Do not line up that number with Postgres **scored** EX (which drops `eval_error` rows).
