# AWS NL2SQL Comparison

Self-contained package to run **six NL2SQL frameworks** against **BIRD Mini-Dev** and **Arctic-Text2SQL-R1-7B** on a 3-role layout (DB + GPU + NL2SQL), locally or on AWS.

This directory is the runnable core of **[LocalNL2SQLPlayground](https://github.com/ArtemK123/LocalNL2SQLPlayground)**. Final experiment runbooks live one level up in [`../experiments/`](../experiments/). Dataset wiring (BIRD is **not** vendored): [`../DATASETS.md`](../DATASETS.md). Prompt / BM25 / Docker knobs: [`../docs/IMPLEMENTATION_DETAILS.md`](../docs/IMPLEMENTATION_DETAILS.md).

Operations runbook: **[AI_OPERATIONS.md](AI_OPERATIONS.md)**. Experiment workflow: **[EXPERIMENTS.md](EXPERIMENTS.md)**.

## Quick start (local)

```powershell
cd nl2sql-comparison
copy env.local.example compose\.env

.\scripts\local\up-db.ps1
.\scripts\local\load_bird_1db.ps1
.\scripts\local\up-gpu.ps1
.\scripts\local\smoke-db.ps1 -Profile 1db
.\scripts\local\smoke-gpu.ps1

.\scripts\local\up-stack.ps1 -Stack langchain -WithUI
.\scripts\local\smoke-stack.ps1 -Stack langchain
```

**Order:** DB → load seed/BIRD → GPU → one stack at a time.

For Experiment A (Formula 1 1-db seed), full BIRD is not required. For AWS / full Mini-Dev: see [`../DATASETS.md`](../DATASETS.md) and set `DATASETS_ROOT` in `compose/.env`.

## Quick start (AWS)

1. `terraform apply` in `terraform/persistent/` then `terraform/compute/`
2. `.\scripts\aws\upload-bird-to-s3.ps1 -ReadBucketFromTfvars` (when `BIRD_dev.sql` is available locally)
3. `.\scripts\aws\deploy-db-from-s3.ps1` — DB + optional full BIRD load from S3
4. `.\scripts\aws\deploy-gpu-from-s3.ps1` — Ollama + Arctic on GPU host (SSM)
5. `.\scripts\aws\start-stack.ps1 -Stack langchain` — one framework smoke (SSM)
6. `.\scripts\aws\smoke-aws-all.ps1` — all six frameworks (SSM, sequential)
7. `.\scripts\aws\stop-system.ps1` when done (retains EBS + S3)

SSH/sync (`sync-to-ec2.ps1`) is optional; prefer SSM scripts when no PEM key is on the laptop.

## Layout

| Path | Role |
|------|------|
| `compose/docker-compose.db.yml` | Local Postgres + network |
| `compose/docker-compose.db.aws.yml` | AWS Postgres on `/data/postgres` EBS |
| `compose/docker-compose.gpu.yml` | Ollama + Arctic |
| `compose/stacks/<name>/` | Per-framework NL2SQL |
| `stacks/<name>/` | Vendored build sources |
| `terraform/persistent/` | 50 GB retained EBS |
| `terraform/compute/` | VPC + 4 EC2 instances |

## Constraints

- One NL2SQL stack at a time on the framework host
- Scored benchmarks use the `harness/` package (UI Playwright and/or HTTP API modes)
- Demo DB passwords in `env.*.example` are intentional lab defaults — change them for any shared/production use
