# Datasets (not vendored)

**BIRD / Mini-Dev SQL dumps and SQLite `dev_databases` are not included in this repository** (size + redistribution constraints). Download them separately and point the package at your local paths.

## What you need

| Asset | Used by | Approx. size | How it is wired |
|-------|---------|--------------|-----------------|
| **Formula 1 seed** (`stack/bird/seed/formula_1_seed.sql`) | Experiment **A** (local 1-db) | ~14 MB | **Included** in this repo for local smoke without full BIRD |
| **BIRD Mini-Dev PostgreSQL dump** (`BIRD_dev.sql`) | Experiments **B** / **C** (AWS DB load) | ~956 MB | Download → `upload-bird-to-s3.ps1` → DB EC2 loads via S3 |
| **Mini-Dev questions + gold** | Harness suites | small | Suite JSON/JSONL under `nl2sql-comparison/harness/test_suites/minidev/` (included) |
| **Mini-Dev SQLite `dev_databases/`** | Optional SQLite Gen-EX eval (study-parity SQLite profiles) | large | Set `sqlite_databases_dir` in experiment profiles |
| **`dev_tables.json`** | LangChain BM25 CREATE-TABLE schema | small | Shipped at `stacks/langchain/langchain_api/data/dev_tables.json` |

## Official sources

1. **BIRD benchmark / Mini-Dev**  
   - Project: [https://bird-bench.github.io/](https://bird-bench.github.io/)  
   - Mini-Dev release (questions, SQLite DBs, metadata): follow the official Mini-Dev download instructions from the BIRD authors (Hugging Face / Google Drive links published with the Mini-Dev paper/repo).  
   - Expected layout after unpack (example):

```text
<DATASETS_ROOT>/
  minidev/
    MINIDEV/
      mini_dev_mysql.json          # or postgresql JSON used by your tooling
      mini_dev_postgresql.json
      tables.json / dev_tables.json
      dev_databases/               # per-db SQLite files for SQLite EX
    MINIDEV_postgresql/
      BIRD_dev.sql                 # full PG dump (~956 MB, 75 tables in public on AWS load)
```

2. **Arctic-Text2SQL-R1-7B weights** (not in git)  
   - Hugging Face (vLLM / Experiment C): [Snowflake/Arctic-Text2SQL-R1-7B](https://huggingface.co/Snowflake/Arctic-Text2SQL-R1-7B)  
   - GGUF Q4 for Ollama (Experiment B SQL stacks): [mradermacher/Arctic-Text2SQL-R1-7B-GGUF](https://huggingface.co/mradermacher/Arctic-Text2SQL-R1-7B-GGUF) — built on GPU via `stack/ollama/ensure-arctic-q4.sh`

## Wire-up checklist

### Local (Experiment A)

```powershell
cd nl2sql-comparison
copy env.local.example compose\.env
# DATASETS_ROOT is only needed for full BIRD load; 1-db uses included formula_1 seed:
.\scripts\local\up-db.ps1
.\scripts\local\load_bird_1db.ps1
```

Optional full local PG load (not required for A):

```powershell
# Place BIRD_dev.sql under DATASETS_ROOT (see env.local.example)
.\scripts\local\load_bird_dev.ps1
```

### AWS (Experiments B / C)

```powershell
cd nl2sql-comparison
# 1) Put BIRD_dev.sql on the laptop under your datasets tree
# 2) Create S3 bucket (name goes into terraform.tfvars / env.aws.example)
.\scripts\aws\upload-bird-to-s3.ps1 -ReadBucketFromTfvars
.\scripts\aws\deploy-db-from-s3.ps1
```

Never `scp` the multi-hundred-MB dump directly to EC2 in normal workflow — use the S3 staging scripts.

### SQLite study-parity eval path

Edit profiles such as `experiments/profiles/arctic-vllm-onepass-10s-full.json`:

```json
"sqlite_databases_dir": "D:/data/BIRD-Mini-Dev/MINIDEV/dev_databases"
```

Use an absolute path to your unpacked Mini-Dev `dev_databases` directory.

## What is intentionally not published

- Full `BIRD_dev.sql`
- Mini-Dev `dev_databases/` SQLite trees
- GGUF / HF model weight caches
- Raw harness `jsonl/` and Playwright `traces/` for every draft run
