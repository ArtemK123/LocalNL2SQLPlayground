# Experiment B — NL2SQL framework selection (AWS)

Compare the six frameworks on the **3-role AWS cluster** (DB + GPU + NL2SQL) with **Arctic** (SQL stacks) and Qwen Coder (Chat2DB/DbGPT after manual GPU switch). This is the **AWS** selection experiment.

## Scope

| Item | Value |
|------|--------|
| Frameworks | all six (one at a time on NL2SQL EC2) |
| SQL model | `arctic-text2sql-r1-7b:q4_k_m` on Ollama (GPU) |
| Chat2DB / DbGPT model | `qwen2.5-coder:14b-instruct-q8_0` via `set-gpu-model.ps1 -ModelProfile general` |
| Database | Full Mini-Dev load into Postgres (`public`, 75 tables) from S3 |
| Default suite | `small_10` (profile); probe with `smoke_3` first |
| Eval DSN | `postgresql://olap:olap@127.0.0.1:55433/bird` (laptop tunnel) |
| Profile | `nl2sql-comparison/experiments/profiles/arctic-small10-all.json` |

## Prerequisites

1. AWS account, CLI auth (`aws sts get-caller-identity`).
2. Terraform apply: `terraform/persistent/` then `terraform/compute/` (copy `*.tfvars.example` → `terraform.tfvars`; **never commit tfvars or PEMs**).
3. BIRD Mini-Dev PG dump on the laptop — see [DATASETS.md](../DATASETS.md).
4. Harness + Playwright on the **laptop** (not on EC2).

## Reproduce

```powershell
cd nl2sql-comparison
aws sts get-caller-identity

# Infra (once)
# terraform -chdir=terraform/persistent apply
# terraform -chdir=terraform/compute apply

.\scripts\aws\ensure-cluster.ps1
.\scripts\aws\upload-bird-to-s3.ps1 -ReadBucketFromTfvars   # first time
.\scripts\aws\deploy-db-from-s3.ps1
.\scripts\aws\deploy-gpu-from-s3.ps1                        # Arctic Q4 on GPU
.\scripts\aws\write-ssh-config.ps1                          # if using SSH tunnels; SSM preferred

# Probe latency (optional)
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/probe-smoke3.json -SkipPublish

# Full six-stack selection suite
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-small10-all.json -SkipPublish
```

Before **chat2db** / **dbgpt** segments, switch GPU model:

```powershell
.\scripts\aws\set-gpu-model.ps1 -ModelProfile general
```

Switch back for SQL stacks:

```powershell
.\scripts\aws\set-gpu-model.ps1 -ModelProfile sql
```

When idle: `.\scripts\aws\stop-system.ps1` (keeps EBS + S3).

## Config pointers

| Concern | Where |
|---------|--------|
| AWS env template | `env.aws.example` |
| Dual-model catalog | `models/README.md`, `models/stack-models.json` |
| Arctic Modelfile | `stack/ollama/Modelfile.arctic-q4_k_m` |
| Orchestrator | `scripts/aws/run-benchmark-aws.ps1`, `EXPERIMENTS.md`, `AI_OPERATIONS.md` (under `nl2sql-comparison/`) |
| Compose on EC2 | same `compose/` tree published via S3 package scripts |

## Wall time / cost

Rough: `small_10` × 6 stacks can take **5–8 hours**. Prefer stopping compute when idle.
