# NL2SQL AWS experiment summary

Generated: 2026-08-09 22:47:43

## langchain_minidev_diverse_10

[
  {
    "count": 10,
    "scored": 9,
    "mean_ex": 0.6666666666666666,
    "mean_soft_f1": 0.6666666666666666,
    "error_rate": {
      "ui_error": 0,
      "eval_error": 0,
      "missing_gold": 0
    },
    "latency_ms": {
      "mean": 3899.5,
      "median": 3286.0,
      "p95": 8263.549999999996
    },
    "wall_ms": {
      "mean": 4037.6,
      "median": 3436.5,
      "p95": 8355.899999999996
    },
    "resources": {},
    "framework": "langchain",
    "suite": "minidev_diverse_10",
    "path": "results/aws_20260809_studyparity_gate/jsonl/<framework>_<suite>.jsonl"
  }
]

framework | n | mean_ex | mean_soft_f1 | mean_latency_ms | p95_latency_ms | ui_err
--- | --- | --- | --- | --- | --- | ---
langchain | 10 | 0.667 | 0.667 | 3900 | 8264 | 0

