# doris-test

Minimal package to reproduce **LangChain + Arctic-Text2SQL-R1-7B (vLLM)** with **Apache Doris** as the predicted-SQL engine (Experiment **D**).

Ingest is **CDC from PostgreSQL OLTP** (Debezium → Kafka → Doris routine load), **not** bulk CSV. Gold Mini-Dev SQL still runs on Postgres; predicted SQL runs on Doris (MySQL protocol).

Parent runbook: [`../experiments/D-langchain-arctic-doris-aws.md`](../experiments/D-langchain-arctic-doris-aws.md).  
SQLite / Postgres study-parity (Experiments A–C) lives in [`../nl2sql-comparison/`](../nl2sql-comparison/).

## Architecture (four roles)

```
Postgres (db, BIRD gold) ──CDC──► Kafka/Debezium + Doris FE/BE (analytics)
                                         │
vLLM Arctic (gpu) ──► LangChain API (nl2sql) ──MySQL :9030──► Doris
                                         │
Laptop harness (dual-DSN): gold=Postgres :55433, pred=Doris :9031
```

NL2SQL does **not** query Postgres. Bring up **GPU only after ODS is healthy** (routine loads caught up).

| Role | Compose | AWS tag |
|------|---------|---------|
| db | `compose/docker-compose.db.yml` | `doris-test-db` |
| analytics | `compose/docker-compose.analytics.yml` | `doris-test-analytics` |
| gpu | `compose/docker-compose.gpu.vllm.yml` | `doris-test-gpu` |
| nl2sql | `compose/stacks/langchain/docker-compose.yml` | `doris-test-nl2sql` |

Ingest definition (committed): `stack/connectors/bird-postgres-source.json`, `stack/bird/init/z99_publications.sql`, `stack/doris/*.sql`. Regenerate after a BIRD load with `scripts/codegen/generate_cdc.py`.

## LangChain knobs that differ from Postgres / SQLite

| Knob | Doris value |
|------|-------------|
| `ARCTIC_SQL_DIALECT` | `mysql` (OmniSQL “Database Engine” + MySQL dialect instructions) |
| `SCHEMA_SOURCE` | `bird_tables` |
| `SQL_EXEC_MODE` | `skip` (API returns SQL; harness executes) |
| `DB_URI` | `mysql+pymysql://root@<DORIS_FE>:9030/bird_minidev_olap` |
| `DB_DIALECT` / `DB_BACKEND` | `mysql` / `doris` |
| `DB_ID_AS_SCHEMA` | `true` |

Universal SQLite→MySQL compiler: `stacks/langchain/langchain_api/app/sql_guard.py` + `dialect.py`. No per-question patches.

## Local (Compose)

Local default LLM is **Qwen** (`env.local.example`). Do not compare those scores to Arctic.

```powershell
cd doris-test
Copy-Item env.local.example compose\.env
# Point DATASETS_ROOT at unpacked Mini-Dev (see ../DATASETS.md)
.\scripts\local\up-db.ps1
.\scripts\local\load_bird_dev.ps1
.\scripts\local\generate-and-up-analytics.ps1   # wait until ODS/routine loads are healthy
.\scripts\local\up-gpu.ps1                      # only after ODS is healthy
.\scripts\local\up-stack-langchain.ps1
.\scripts\local\smoke-cluster.ps1
```

## AWS (Arctic + vLLM, Mini-Dev 500)

Copy `terraform/*/terraform.tfvars.example` → `terraform.tfvars` (**do not commit**). Then:

```powershell
cd doris-test
aws sts get-caller-identity
# terraform -chdir=terraform/persistent apply
# terraform -chdir=terraform/compute apply
.\scripts\aws\ensure-cluster.ps1
.\scripts\aws\upload-bird-to-s3.ps1
.\scripts\aws\deploy-db-from-s3.ps1
.\scripts\aws\deploy-analytics-from-s3.ps1      # CDC snapshot; 30–90 min
.\scripts\aws\deploy-gpu-vllm-from-s3.ps1       # after ODS healthy
.\scripts\aws\deploy-nl2sql-from-s3.ps1
.\scripts\aws\write-ssh-config.ps1
.\scripts\aws\preflight-eval-health.ps1
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-vllm-studyparity-doris-diverse10.json -SkipPublish
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-vllm-studyparity-doris-full.json -SkipPublish
```

Score on **laptop tunnels**, not the nl2sql host (gold Postgres is SG-blocked from nl2sql). See [EXPERIMENTS.md](EXPERIMENTS.md).

## Harness flags (published run)

```text
doris-test-harness run-api --suite full
  --eval-mode dual_dsn
  --ex-mode bird
  --gold-dsn postgresql://olap:olap@127.0.0.1:55433/bird
  --pred-dsn mysql://root@127.0.0.1:9031/bird_minidev_olap
  --api-url http://127.0.0.1:8011/v1/chat
  --workers 2 --timeout 10
```

Reference scores: `results/doris_20260815_113514/` (`manifest.json`, `summary.md`). The 500-question jsonl is not vendored.
