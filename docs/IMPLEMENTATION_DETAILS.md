# Implementation details (reproduction)

Concrete knobs for independent reproduction of the final experiments. Paths are relative to `nl2sql-comparison/` unless noted.

## 1. Prompt templates (LangChain + Arctic)

Source: `stacks/langchain/langchain_api/app/agent.py`.

### OmniSQL / Arctic SQL generation (`ARCTIC_SQL_PROMPT`)

- **System:** *"You are a data science expert…"* (generate a valid SQL query for the given schema + question).
- **Human fields:** `Database Engine` (`SQLite`, `PostgreSQL`, or MySQL/Doris from `ARCTIC_SQL_DIALECT`), `Database Schema` (`{schema_reference}`), `Question` (`{question_with_evidence}`), instructions (SELECT only asked columns; think step-by-step), output format, *"Start your reply with: Let me solve this step by step."*
- **PostgreSQL dialect hint** (when engine is PostgreSQL): use PostgreSQL syntax; double-quote identifiers only when needed; no SQLite backticks.
- **MySQL / Doris dialect** (Experiment D): `doris-test/stacks/langchain/langchain_api/app/dialect.py` demands `DATE_FORMAT` / `CONCAT` / `NOW` / backticks and forbids `strftime` / `||`.

### Repair / answer / reasoning prompts

Same file: `ARCTIC_REPAIR_PROMPT`, `ANSWER_PROMPT`, `REASONING_PROMPT`. Study-parity scored runs set `NL2SQL_FAST_MODE=true` and `SQL_REPAIR_MAX_RETRIES=0` so the primary path is one-pass SQL generation (no repair / summarize loop).

### Ollama Modelfile SYSTEM (Experiment B Q4 Arctic)

`stack/ollama/Modelfile.arctic-q4_k_m`:

- `PARAMETER temperature 0`
- `PARAMETER num_predict 1024`
- SYSTEM string matches the OmniSQL expert preamble (CoT + \`\`\`sql; do not force SQL-only `</sql>` stop).

### vLLM one-pass decoding (Experiments B*/C)

Controlled by env (see `env.aws.example` + LangChain compose):

| Variable | Study-parity value | Role |
|----------|-------------------|------|
| `ARCTIC_SQL_FENCE_PREFILL` | `true` | Prefill assistant with SQL fence; continue final message |
| `ARCTIC_SQL_DIALECT` | `sqlite`, `postgresql`, or `mysql` (D) | Prompt engine label |
| `OLLAMA_NUM_PREDICT` / vLLM max tokens | `512` (one-pass) | Cap generation length |
| `LLM_HTTP_TIMEOUT_SEC` | `20` | HTTP client timeout to vLLM |
| Harness `timeout_sec` | `10` | Per-question client SLA in profiles |

\*Experiment B default profile uses **Ollama Q4 Arctic** with long UI timeouts (`900s`); Experiment C uses **vLLM** + API mode + 10s study-parity.

## 2. Model parameters

### Local framework selection (Experiment A)

From `env.local.example` → `compose/.env`:

| Parameter | Value |
|-----------|--------|
| Primary / fallback LLM | `qwen2.5:7b-instruct` |
| Embeddings | `nomic-embed-text` |
| `OLLAMA_NUM_CTX` | `4096` |
| `OLLAMA_NUM_PREDICT` | `512` |
| `OLLAMA_NUM_PARALLEL` | `2` |
| LangChain schema mode (local defaults) | heuristic shortlist; see local example (`SCHEMA_FINAL_TOP_K=5`) |

Arctic is **not** used on the laptop path (VRAM / policy).

### AWS framework selection (Experiment B)

From `env.aws.example` + `models/stack-models.json`:

| Stack group | Model |
|-------------|--------|
| SQL stacks (langchain, premsql, vanna, wrenai) | `arctic-text2sql-r1-7b:q4_k_m` (Ollama) |
| chat2db / dbgpt (general) | `qwen2.5-coder:14b-instruct-q8_0` |
| Switch | `scripts/aws/set-gpu-model.ps1 -ModelProfile sql\|general` |

Profile: `experiments/profiles/arctic-small10-all.json` — suite `small_10`, timeout `900`, all six stacks.

### LangChain + Arctic on PostgreSQL (Experiment C)

| Parameter | Value |
|-----------|--------|
| Model | `Snowflake/Arctic-Text2SQL-R1-7B` |
| Backend | **vLLM** (`LLM_BACKEND=vllm`, OpenAI-compatible on GPU `:11434`) |
| GPU | `g6.xlarge` (1× L4 24 GB) — see Terraform examples |
| `VLLM_MAX_MODEL_LEN` | `4096` |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.90` |
| Suite | `full` (Mini-Dev **N=500**) |
| Mode | `api` (`run-api`), `workers=2` |
| `timeout_sec` | `10` |
| `eval_engine` | `postgres` |
| `ex_mode` | `bird` |
| `arctic_sql_dialect` | `postgresql` |
| Profile | `experiments/profiles/arctic-vllm-studyparity-postgres-full.json` |

Reference SQLite study-parity (same generation knobs, SQLite eval): `arctic-vllm-onepass-10s-full.json`.

## 3. Retrieval / BM25 (schema linking)

Source: `stacks/langchain/langchain_api/app/schema_bm25.py` + `config.py`.

| Setting | Study-parity (C) | Notes |
|---------|------------------|-------|
| `SCHEMA_SOURCE` | `bird_tables` | CREATE TABLE text from `dev_tables.json` |
| `BIRD_TABLES_JSON` | `/app/data/dev_tables.json` | Bundled in LangChain image |
| `SCHEMA_SELECTION_ENABLED` | `true` | |
| `SCHEMA_SELECTOR_MODE` | `bm25` | Pure Okapi BM25 (not hybrid/LLM) |
| `SCHEMA_FINAL_TOP_K` | `8` | Top tables kept |
| `SCHEMA_BM25_INCLUDE_FK` | `true` | Expand with direct FK neighbors |
| `SCHEMA_SHORTLIST_TOP_M` | `25` | Upstream shortlist size |
| BM25 `k1` | `1.5` | In `Bm25Index` |
| BM25 `b` | `0.75` | In `Bm25Index` |
| Query text | question **+** evidence | Tokenized with camel/snake + light plural variants |

WrenAI (framework comparison) uses separate retrieval knobs in env examples:

- `WREN_TABLE_RETRIEVAL_SIZE=75`
- `WREN_TABLE_COLUMN_RETRIEVAL_SIZE=500`

## 4. Docker / Compose

| File | Role |
|------|------|
| `compose/docker-compose.db.yml` | Local Postgres + `nl2sql-comparison-net` |
| `compose/docker-compose.db.aws.yml` | AWS DB on persistent EBS `/data/postgres` |
| `compose/docker-compose.gpu.yml` | Ollama GPU |
| `compose/docker-compose.gpu.vllm.yml` | vLLM GPU (Arctic HF) |
| `compose/docker-compose.gpu.cpu.yml` | CPU fallback Ollama |
| `compose/stacks/<framework>/docker-compose.yml` | One NL2SQL framework at a time |
| `stack/bird/init/*.sql`, `z99_grants.sh` | Roles / grants for bird + olap + nl2sql_ro |
| `doris-test/compose/docker-compose.analytics.yml` | Experiment D: Kafka + Debezium + Doris FE/BE (CDC from Postgres, not CSV) |

**Policy:** only one framework compose project on the NL2SQL host at a time.

Example LangChain study-parity env block: `compose/stacks/langchain/docker-compose.yml` (SCHEMA_* and ARCTIC_* variables listed above).

## 5. Terraform (AWS)

| Stack | Path |
|-------|------|
| Persistent 50 GB EBS | `terraform/persistent/` |
| VPC + bastion + db + gpu + nl2sql | `terraform/compute/` |

Copy `terraform.tfvars.example` → `terraform.tfvars` (**do not commit**). Provide your own key pair PEM outside the repo (`key_name` in tfvars). SSM is the default deploy path; SSH is optional for debug.

## 6. Harness

| Item | Detail |
|------|--------|
| Package | `harness/` (`pip install -e ".[ui]"`) |
| Local DSN | `postgresql://olap:olap@127.0.0.1:55432/bird` |
| AWS eval DSN | `postgresql://olap:olap@127.0.0.1:55433/bird` (tunnel) |
| Suites | `harness/test_suites/minidev/` (`smoke_3`, `small_10`, `medium_25`, `full`, …) |
| Metrics | Execution accuracy (EX), soft_f1, latency |
| Orchestrator | `scripts/aws/run-benchmark-aws.ps1` |

Committed reference scores for Experiment C: `results/aws_20260809_studyparity_postgres/` (`manifest.json`, `summary.md`).

## 7. Apache Doris (Experiment D)

Package root: `doris-test/` (not `nl2sql-comparison/`). Gold remains Postgres; predicted SQL runs on Doris after CDC.

| Parameter | Value |
|-----------|--------|
| Model | `Snowflake/Arctic-Text2SQL-R1-7B` |
| Backend | **vLLM** (`LLM_BACKEND=vllm`) |
| `ARCTIC_SQL_DIALECT` | `mysql` |
| `SCHEMA_SOURCE` | `bird_tables` |
| `SQL_EXEC_MODE` | `skip` |
| `DB_URI` | `mysql+pymysql://root@<DORIS_FE>:9030/bird_minidev_olap` |
| Harness | `doris-test-harness` `--eval-mode dual_dsn --ex-mode bird` |
| Gold DSN | `postgresql://olap:olap@127.0.0.1:55433/bird` |
| Pred DSN | `mysql://root@127.0.0.1:9031/bird_minidev_olap` |
| Suite | `full` (Mini-Dev **N=500**); gate `minidev_diverse_10` |
| Timeout / workers | **10 s** / **2** |
| Profile | `doris-test/experiments/profiles/arctic-vllm-studyparity-doris-full.json` |

MySQL dialect instructions: `stacks/langchain/langchain_api/app/dialect.py` (`MYSQL_DIALECT_INSTRUCTIONS`). Universal SQLite→MySQL compiler: `sql_guard.py` (`strftime`→`DATE_FORMAT`, `||`→`CONCAT`, `IIF`→`IF`, reserved-table backticks). No per-question patches.

Ingest: Postgres OLTP → Debezium (`stack/connectors/bird-postgres-source.json`) → Kafka → Doris routine loads (`stack/doris/20_routine_loads.sql`). **Not** bulk CSV. Start GPU only after ODS is healthy.

CDC compose: `doris-test/compose/docker-compose.analytics.yml`. Four-role Terraform examples: `doris-test/terraform/*/terraform.tfvars.example`.

Committed reference: `doris-test/results/doris_20260815_113514/` (overall EX **0.42**, EX among `dual_ok` **0.468**). Methodology: `doris-test/experiments/arctic-vllm-doris-vs-sqlite-postgres.md`.
