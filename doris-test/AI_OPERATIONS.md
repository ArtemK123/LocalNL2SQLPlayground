# Doris-test — operations runbook

## Deploy order

1. **Persistent EBS** — `terraform/persistent` (db_pgdata + analytics_doris_be)
2. **Compute** — `terraform/compute` (bastion, db, gpu, analytics, nl2sql)
3. **DB** — `deploy-db-from-s3.ps1` → BIRD load via `stage-bird-assets.sh`
4. **Codegen** (laptop or SSM) — `generate_cdc.py` then re-publish package if artifacts changed
5. **Analytics** — `deploy-analytics-from-s3.ps1` (Debezium snapshot + Doris routine loads; 30–90 min for full minidev). Wait until ODS is healthy.
6. **GPU** — `deploy-gpu-vllm-from-s3.ps1` (Arctic OpenAI :11434) **after ODS is healthy** (or `deploy-gpu-from-s3.ps1` for Ollama)
7. **NL2SQL** — `deploy-nl2sql-from-s3.ps1 -LlmBackend vllm` (when using vLLM)
8. **Smoke** — `smoke-cluster.ps1`, `smoke-replication-parity.sh`
9. **Experiment** — `run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-vllm-studyparity-doris-diverse10.json`

## Port-forward matrix (via bastion)

| Service | Host | Port |
|---------|------|------|
| PostgreSQL (gold eval) | db | 5432 → local 55433 |
| Doris FE HTTP | analytics | 8030 |
| Doris MySQL | analytics | 9030 → local 9031 |
| LangChain API | nl2sql | 8011 |
| Chainlit | nl2sql | 8501 |
| Ollama / vLLM | gpu | 11434 |

SSH config: `.\scripts\aws\write-ssh-config.ps1` → `~/.ssh/doris_test_ssh_config`

**Scoring host:** run dual-DSN on the **laptop** (tunnels above) or on **analytics**. Do not score gold PG from nl2sql under default SG (`ALLOW_NL2SQL_GOLD_SCORE=1` required to override). Preflight: `.\scripts\aws\preflight-eval-health.ps1`.

## Security groups

- DB:5432 **only** from analytics (not nl2sql)
- Analytics:9030 from nl2sql
- GPU:11434 from nl2sql

## S3 layout

`s3://{bucket}/doris-test/package/{version}/package.tgz`  
`s3://{bucket}/doris-test/package/{version}/BIRD_dev.sql`
