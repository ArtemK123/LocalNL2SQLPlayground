# NL2SQL AWS experiment summary

Generated: 2026-08-09 23:08:30

## langchain_full

[
  {
    "count": 500,
    "scored": 477,
    "mean_ex": 0.5618448637316562,
    "mean_soft_f1": 0.580337961841708,
    "error_rate": {
      "ui_error": 0,
      "eval_error": 18,
      "missing_gold": 0
    },
    "latency_ms": {
      "mean": 3629.16,
      "median": 3328.0,
      "p95": 6539.0
    },
    "wall_ms": {
      "mean": 3781.674,
      "median": 3491.0,
      "p95": 6684.05
    },
    "resources": {},
    "framework": "langchain",
    "suite": "full",
    "path": "results/aws_20260809_studyparity_full/jsonl/<framework>_<suite>.jsonl"
  }
]

framework | n | mean_ex | mean_soft_f1 | mean_latency_ms | p95_latency_ms | ui_err
--- | --- | --- | --- | --- | --- | ---
langchain | 500 | 0.562 | 0.580 | 3629 | 6539 | 0

