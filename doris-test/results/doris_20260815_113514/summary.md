# Arctic vLLM Doris full minidev 500 (MySQL dialect prompt + SQLite→MySQL compiler)

- **run_id:** doris_20260815_113514
- **eval_mode:** dual_dsn
- **ex_mode:** bird (positional; ignore aliases)
- **model:** Snowflake/Arctic-Text2SQL-R1-7B
- **schema_source:** bird_tables
- **sql_exec_mode:** skip
- **fence prefill / repair / evidence:** on / 0 / on
- **prompt:** MYSQL_DIALECT_INSTRUCTIONS (DATE_FORMAT/CONCAT/NOW; no strftime/||)
- **sql_guard:** universal SQLite→MySQL compiler (no question-aware cheats)
- **n:** 500
- **n_api_ok:** 488
- **n_gold_ok:** 487
- **n_pred_ok:** 450
- **n_dual_ok:** 449
- **ex_among_dual_ok:** 0.468 (210/449)
- **ex_over_all:** 0.42 (210/500)
- **soft_f1_mean_among_dual_ok:** 0.490
- **latency_ms_mean:** 3839
- **n_alias_mismatch:** 90 (all EX=true under bird)

## vs previous full run `doris_20260814_201420`

| Metric | 201420 (old) | **113514 (new)** |
|--------|-------------:|-----------------:|
| n_api_ok | 487 | **488** |
| n_gold_ok | 486 | **487** |
| n_pred_ok | 382 | **450** |
| n_dual_ok | 381 | **449** |
| EX among dual_ok | 0.472 (180/381) | **0.468 (210/449)** |
| EX overall | 0.36 (180/500) | **0.42 (210/500)** |
| soft_f1 among dual_ok | 0.495 | 0.490 |
| latency_ms mean | 3646 | 3839 |
| pred_fail | 105 | **38** |
| strftime pred_err | 34 | **0** |
| MATCH/SETS pred_err | 24 | **1 MATCH** |

Overall EX now matches same-engine Postgres study-parity **0.420**. Dual_ok EX is slightly lower because 68 extra questions now execute on Doris (many are generation-wrong, not dialect-blocked).

## Failures

- API: 10 timed out @10s, 2 HTTP 400
- Gold PG: 1 subquery returned more than one row
- Pred Doris (38): agg select-list 12, unknown column 12, syntax 4, leftover scalar subquery 3, concat 2, reserved MATCH 1, other 4
- Generated SQL: 46 `DATE_FORMAT`, 4 `CONCAT`, **0 `strftime`**, **0 `||`**

## Paths

- results: `doris-test/results/doris_20260815_113514/`
- jsonl: `jsonl/langchain_full.jsonl`
- manifest: `manifest.json`
