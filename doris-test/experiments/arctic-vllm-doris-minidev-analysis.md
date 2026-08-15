# Arctic vLLM × Doris — minidev analysis index

**Current comparison report:** [`arctic-vllm-doris-vs-sqlite-postgres.md`](arctic-vllm-doris-vs-sqlite-postgres.md)  
**Primary run:** `doris_20260815_113514` (full BIRD minidev, N=500, dialect prompt + universal SQLite→MySQL compiler)  
**Artifacts:** `doris-test/results/doris_20260815_113514/` (`jsonl/langchain_full.jsonl`, `summary.md`, `manifest.json`)

Do **not** cite this file as the 201420-only story. The numbers below are a changelog so older links still resolve.

---

## Latest headline (`doris_20260815_113514`)

| Metric | Value |
|--------|------:|
| n / n_api_ok / n_gold_ok / n_pred_ok / n_dual_ok | 500 / 488 / 487 / 450 / 449 |
| EX among dual_ok | **0.468** (210/449) |
| EX overall (Strict-style) | **0.42** (210/500) |
| soft_f1 among dual_ok | 0.490 |
| latency_ms mean | 3839 |
| pred_fail | 38 (`strftime` 0, MATCH/SETS 0 in jsonl) |

Same-engine baselines (Aug 9, `aws/nl2sql-comparison`, Arctic vLLM one-pass 10s, study-parity): SQLite Strict EX **0.536** (`aws_20260809_studyparity_full`), Postgres Strict EX **0.420** (`aws_20260809_studyparity_postgres`). Doris is **dual-DSN** (gold = Postgres, pred = Doris) — overall EX is the comparable /500 number; EX among `dual_ok` is the cross-engine rate. Details and the systematic error taxonomy are in the comparison report.

---

## Run log

| Run ID | Suite | Role |
|--------|-------|------|
| `doris_20260813_083653` | `minidev_diverse_10` | First fair dual-DSN + LLM-judge (search_path remapped) |
| `doris_20260814_113124` | `minidev_diverse_10` | Pre–study-parity; unknown-table / wrong-db; Arctic-as-judge abstains |
| `doris_20260814_170306` | `minidev_diverse_10` | Study-parity `bird_tables` + qualify; classic dual-DSN |
| `doris_20260814_201420` | `full` | Study-parity + bird EX; **no** dialect compiler — overall EX **0.36**, pred_ok **382**, 105 pred_error |
| **`doris_20260815_113514`** | **`full`** | **Prompt + universal compiler; current primary** — overall EX **0.42**, pred_ok **450**, 38 pred_error |

Compiler vs `201420`: `strftime` pred_err 34→0, MATCH/SETS 24→0 (jsonl), pred_ok 382→450. EX among `dual_ok` 0.472→0.468 (more executable rows, many still generation-wrong). Methodology, three-way tables, and residual taxonomy: the comparison report.

---

## Archive: `doris_20260814_201420` (pre-compiler)

Kept so citations of this path still have the old funnel. **Not** the comparison source.

| Metric | Value |
|--------|------:|
| n_api_ok / n_gold_ok / n_pred_ok / n_dual_ok | 487 / 486 / 382 / 381 |
| EX among dual_ok | 0.472 (180/381) |
| EX overall | 0.36 (180/500) |
| pred_fail | 105 (`strftime` 34, syntax/MATCH/SETS 28, unknown column 27, …) |

Pred-exec was dominated by SQLite `strftime` and unquoted reserved identifiers (`match`, `sets`). LLM-judge was not primary: Arctic-as-judge abstained on diverse10 (`judge_parse_error: no JSON object`).

Reproduce the current full run:

```powershell
cd doris-test
.\scripts\aws\write-ssh-config.ps1
.\scripts\aws\preflight-eval-health.ps1
.\scripts\aws\run-benchmark-aws.ps1 `
  -Profile experiments/profiles/arctic-vllm-studyparity-doris-full.json
```
