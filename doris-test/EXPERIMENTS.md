# Doris-test experiments

Public runbook: [`../experiments/D-langchain-arctic-doris-aws.md`](../experiments/D-langchain-arctic-doris-aws.md).

## Campaign reports

| Report | Summary |
|--------|---------|
| [`arctic-vllm-doris-vs-sqlite-postgres.md`](experiments/arctic-vllm-doris-vs-sqlite-postgres.md) | Methodology + three-way EX + Doris error analysis |
| [`arctic-vllm-doris-minidev-analysis.md`](experiments/arctic-vllm-doris-minidev-analysis.md) | Run index (primary `doris_20260815_113514`; pre-compiler ablation 0.36) |
| [`arctic-vllm-doris-deploy-runtime-metrics.md`](experiments/arctic-vllm-doris-deploy-runtime-metrics.md) | Four-role deploy / VRAM / start-from-stopped |

Primary run **`doris_20260815_113514`** (MySQL dialect prompt + universal SQLite→MySQL compiler): overall EX **0.42** (210/500); EX among `dual_ok` **0.468** (210/449). Same-engine baselines: SQLite Strict **0.536**, Postgres Strict **0.420**.

## Scoring host (critical)

Gold PostgreSQL (`:5432`) is **not** reachable from `nl2sql` under the default security group. Scoring gold from nl2sql yields connection timeouts → opaque EX=0.

| Path | Gold PG | Doris pred | When |
|------|---------|------------|------|
| **Laptop tunnels (preferred)** | `127.0.0.1:55433` → db | `127.0.0.1:9031` → analytics:9030 | Default for `run-benchmark-aws.ps1` |
| **Analytics host** | private db:5432 (SG ok) | localhost:9030 | `ssm-run-harness.sh` with `SCORE_HOST=analytics` |
| **nl2sql** | blocked | analytics:9030 | **Refused** unless `ALLOW_NL2SQL_GOLD_SCORE=1` |

```powershell
.\scripts\aws\write-ssh-config.ps1
.\scripts\aws\preflight-eval-health.ps1
```

## Evaluation contract

| Flag | Published value |
|------|-----------------|
| `--eval-mode` | `dual_dsn` (gold Postgres, pred Doris) |
| `--ex-mode` | `bird` (positional set of tuples, ignore aliases) |
| `--gold-dsn` | `postgresql://olap:olap@127.0.0.1:55433/bird` |
| `--pred-dsn` | `mysql://root@127.0.0.1:9031/bird_minidev_olap` |
| suite | `full` (Mini-Dev 500) or `minidev_diverse_10` (gate) |

`--ex-mode strict` (name-based) is an ablation only.

Fair generation is **OmniSQL MySQL instructions + a universal SQLite→MySQL compiler**. `sql_guard` must not contain per-question patches.

## Reproduce (Arctic + vLLM)

```powershell
cd doris-test
.\scripts\aws\ensure-cluster.ps1
.\scripts\aws\deploy-gpu-vllm-from-s3.ps1 -SkipPublish
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-studyparity-doris-diverse10.json `
  -SkipPublish
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-studyparity-doris-full.json `
  -SkipPublish
```

### Manual harness

```powershell
cd doris-test/harness
py -3 -m pip install -e .
doris-test-harness run-api --suite full `
  --eval-mode dual_dsn `
  --ex-mode bird `
  --gold-dsn "postgresql://olap:olap@127.0.0.1:55433/bird" `
  --pred-dsn "mysql://root@127.0.0.1:9031/bird_minidev_olap" `
  --api-url http://127.0.0.1:8011/v1/chat `
  --workers 2 --timeout 10
```

Harness summaries report `n_api_ok`, `n_gold_ok`, `n_pred_ok`, `n_dual_ok`, `ex_among_dual_ok`. Do not treat API/gold failures as soft_f1=0 “true zeros”.

## Tunnel ports

| Service | Local |
|---------|-------|
| PostgreSQL gold | `55433` |
| Doris MySQL pred | `9031` |
| LangChain API | `8011` |
| vLLM | `11434` |

## Results git policy

- Commit: `results/<run_id>/manifest.json`, `summary.md`
- Do not commit: `results/**/jsonl/`
