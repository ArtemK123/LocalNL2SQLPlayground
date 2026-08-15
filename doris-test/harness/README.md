# doris-test harness

Flexible EX for `doris-test`: gold on PostgreSQL, predictions on Doris (MySQL). Parent runbook: [`../../experiments/D-langchain-arctic-doris-aws.md`](../../experiments/D-langchain-arctic-doris-aws.md).

## Modes

| `--eval-mode` | Meaning |
|---------------|---------|
| `dual_dsn` | Gold PG + pred Doris; **bird** EX (positional) / soft_f1; `--ex-mode strict` for name-based |
| `dual_dsn_llm_judge` | Same exec path + LLM logical-equivalence judge (primary for Doris↔PG) |
| `postgres` / `sqlite` | Single-engine EX |

`--ex-mode bird` (default) ignores aliases (`?column?` vs `percentage`). `--ex-mode strict` matches columns by name.

## Classic dual-DSN (laptop tunnels)

```powershell
pip install -e .
doris-test-harness run-api --suite smoke_3 `
  --eval-mode dual_dsn `
  --ex-mode bird `
  --gold-dsn "postgresql://olap:olap@127.0.0.1:55433/bird" `
  --pred-dsn "mysql://root@127.0.0.1:9031/bird_minidev_olap" `
  --api-url http://127.0.0.1:8011/v1/chat
```

## LLM-judge

```powershell
doris-test-harness run-api --suite minidev_diverse_10 `
  --eval-mode dual_dsn_llm_judge `
  --gold-dsn "postgresql://olap:olap@127.0.0.1:55433/bird" `
  --pred-dsn "mysql://root@127.0.0.1:9031/bird_minidev_olap" `
  --judge-base-url http://127.0.0.1:11434 `
  --judge-model Snowflake/Arctic-Text2SQL-R1-7B
```

Each judged record stores `judge_prompt_version`, `judge_model`, `judge_inputs_hash`.

## Offline re-score

```powershell
doris-test-harness rescore `
  --jsonl path\to\run.jsonl `
  --suite minidev_diverse_10 `
  --eval-mode dual_dsn `
  --ex-mode bird `
  --gold-dsn "postgresql://olap:olap@127.0.0.1:55433/bird" `
  --pred-dsn "mysql://root@127.0.0.1:9031/bird_minidev_olap" `
  --skip-without-pred
```

Old jsonl without `gold_rows`/`pred_rows` must re-execute SQL. `--ex-mode` still applies after re-exec.

See `../EXPERIMENTS.md` for scoring-host rules and methodology.
