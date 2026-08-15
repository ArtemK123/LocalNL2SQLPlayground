# LocalNL2SQLPlayground

Public reproducibility package for the **final** LocalNL2SQL experiments (framework selection + LangChain/Arctic evaluation).

| Repo | Role |
|------|------|
| **This repository** ([LocalNL2SQLPlayground](https://github.com/ArtemK123/LocalNL2SQLPlayground)) | Code, configs, Docker/Terraform, harness, and instructions to reproduce **final** published experiments only |
| Private research workspace | Full experimental lab: drafts, intermediate runs, AI notes, large datasets, credentials, all reports |

This repo intentionally omits: draft prototypes, AI temp files, AWS credentials / `.env` secrets, and the full BIRD dataset (too large). See [DATASETS.md](DATASETS.md) to wire BIRD/Mini-Dev locally.

## Final experiments

| ID | Experiment | Entry doc |
|----|------------|-----------|
| **A** | Selection of NL2SQL framework — **local** deployment | [experiments/A-framework-selection-local.md](experiments/A-framework-selection-local.md) |
| **B** | Selection of NL2SQL framework — **AWS** deployment | [experiments/B-framework-selection-aws.md](experiments/B-framework-selection-aws.md) |
| **C** | Chosen **LangChain + Arctic** on AWS — **PostgreSQL** (study-parity Mini-Dev) | [experiments/C-langchain-arctic-postgres-aws.md](experiments/C-langchain-arctic-postgres-aws.md) |
| **D** | Chosen **LangChain + Arctic** on AWS — **Apache Doris** (dual-DSN Mini-Dev) | [experiments/D-langchain-arctic-doris-aws.md](experiments/D-langchain-arctic-doris-aws.md) |

Implementation knobs reviewers typically ask for (prompt templates, model parameters, BM25/retrieval, Docker) are collected in [docs/IMPLEMENTATION_DETAILS.md](docs/IMPLEMENTATION_DETAILS.md).

## Package layout

```
LocalNL2SQLPlayground/
  README.md
  DATASETS.md
  docs/IMPLEMENTATION_DETAILS.md
  experiments/          # reproduction runbooks for A/B/C/D
  nl2sql-comparison/    # SQLite / Postgres package (Compose, harness, Terraform, profiles)
  doris-test/           # Doris dual-DSN package (CDC compose, LangChain MySQL, dual-DSN harness)
```

SQLite/Postgres code lives under [`nl2sql-comparison/`](nl2sql-comparison/). Doris (Experiment D) lives under [`doris-test/`](doris-test/).

## Quick start

```powershell
git clone https://github.com/ArtemK123/LocalNL2SQLPlayground.git
cd LocalNL2SQLPlayground\nl2sql-comparison
copy env.local.example compose\.env   # local Experiment A
# Follow experiments/A-*.md, B-*.md, C-*.md, or D-*.md
```

**Prerequisites (typical):** Docker Desktop, PowerShell 7+, Python 3.13, Playwright (for UI harness), AWS CLI + Terraform (Experiments B/C/D).

## License / upstream

NL2SQL frameworks are vendored or wrapped under `nl2sql-comparison/stacks/` with their own licenses. BIRD Mini-Dev must be obtained from the official BIRD project (see [DATASETS.md](DATASETS.md)).
