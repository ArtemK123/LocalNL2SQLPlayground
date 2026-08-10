# NL2SQL AWS experiment summary

Generated: 2026-08-09 23:46:01

## langchain_full

[
  {
    "count": 500,
    "scored": 345,
    "mean_ex": 0.6086956521739131,
    "mean_soft_f1": 0.6236655871756489,
    "error_rate": {
      "ui_error": 0,
      "eval_error": 148,
      "missing_gold": 0
    },
    "latency_ms": {
      "mean": 3613.808,
      "median": 3276.5,
      "p95": 6635.25
    },
    "wall_ms": {
      "mean": 3763.706,
      "median": 3430.0,
      "p95": 6785.0
    },
    "resources": {},
    "framework": "langchain",
    "suite": "full",
    "path": "results/aws_20260809_studyparity_postgres/jsonl/<framework>_<suite>.jsonl"
  }
]

framework | n | mean_ex | mean_soft_f1 | mean_latency_ms | p95_latency_ms | ui_err
--- | --- | --- | --- | --- | --- | ---
langchain | 500 | 0.609 | 0.624 | 3614 | 6635 | 0

