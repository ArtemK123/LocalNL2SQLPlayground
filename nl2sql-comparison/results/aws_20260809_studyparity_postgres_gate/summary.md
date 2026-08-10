# NL2SQL AWS experiment summary

Generated: 2026-08-09 23:21:19

## langchain_minidev_diverse_10

[
  {
    "count": 10,
    "scored": 8,
    "mean_ex": 0.625,
    "mean_soft_f1": 0.625,
    "error_rate": {
      "ui_error": 0,
      "eval_error": 1,
      "missing_gold": 0
    },
    "latency_ms": {
      "mean": 4187.9,
      "median": 3527.5,
      "p95": 8446.399999999996
    },
    "wall_ms": {
      "mean": 4339.3,
      "median": 3715.5,
      "p95": 8539.999999999996
    },
    "resources": {},
    "framework": "langchain",
    "suite": "minidev_diverse_10",
    "path": "results/aws_20260809_studyparity_postgres_gate/jsonl/<framework>_<suite>.jsonl"
  }
]

framework | n | mean_ex | mean_soft_f1 | mean_latency_ms | p95_latency_ms | ui_err
--- | --- | --- | --- | --- | --- | ---
langchain | 10 | 0.625 | 0.625 | 4188 | 8446 | 0

