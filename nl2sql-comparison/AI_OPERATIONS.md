# AI Operations: NL2SQL Comparison Cluster

Deterministic runbook for agents and operators. Package root: `nl2sql-comparison/`.

**Do not** invoke `battleground-harness` in v1.

## Tunables

| Location | Variables |
|----------|-----------|
| `terraform/persistent/terraform.tfvars` | `aws_region`, `project_name` |
| `terraform/compute/terraform.tfvars` | `allowed_ssh_cidr`, `key_name`, `persistent_volume_id`, `bird_dataset_*`, instance types, spot flags. **GPU:** `gpu_instance_type = "g5.xlarge"` (operational; `g6.xlarge` when Spot capacity exists in subnet AZ). |
| `compose/.env` | `BIRD_PG_HOST`, `OLLAMA_HOST`, model catalog (`OLLAMA_SQL_MODEL`, `OLLAMA_GENERAL_MODEL`, `OLLAMA_ACTIVE_MODEL`) |

**Model policy (mandatory):**

| Environment | Env template | Active 7B model |
|-------------|--------------|-----------------|
| **Local laptop** | `env.local.example` → `compose/.env` | `qwen2.5:7b-instruct` |
| **AWS cluster** | `env.aws.example` on EC2 roles | **Arctic** after deploy; **manual switch** via `set-gpu-model.ps1` |

**AWS dual-model catalog** (one 7B in VRAM at a time; `nomic-embed-text` may coexist):

| Variable | Default | Role |
|----------|---------|------|
| `OLLAMA_SQL_MODEL` | `a-kore/Arctic-Text2SQL-R1-7B` | SQL stacks (langchain, dbgpt, …) |
| `OLLAMA_GENERAL_MODEL` | `qwen2.5:7b-instruct` | Chat2DB |
| `OLLAMA_ACTIVE_MODEL` | Arctic | Runtime on GPU; updated by deploy/switch |

```powershell
# Switch before Chat2DB (lazy-pulls Qwen on first use)
.\scripts\aws\set-gpu-model.ps1 -ModelProfile general

# Switch back for SQL stacks
.\scripts\aws\set-gpu-model.ps1 -ModelProfile sql
```

Do not point local harness smokes at Arctic unless explicitly debugging. Restart GPU + stacks after changing the active model.

## Phase 0: Prerequisites

```powershell
terraform -version
aws sts get-caller-identity
docker version
```

Success: all commands exit 0.

**Before every deploy or smoke** (Spot instances can disappear):

```powershell
cd nl2sql-comparison
.\scripts\aws\ensure-cluster.ps1
```

Required roles: **db**, **gpu**, **nl2sql** (bastion optional for SSM). If **gpu** is missing/terminated, NL2SQL smokes will fail silently against a stale `OLLAMA_HOST` from Terraform — always run preflight first.

```powershell
cd terraform\compute
terraform apply -auto-approve
cd ..\..
.\scripts\aws\deploy-gpu-from-s3.ps1 -SkipPublish
```

## Phase 1: Local smoke

```powershell
cd nl2sql-comparison
copy env.local.example compose\.env   # qwen2.5:7b-instruct — not env.aws.example (Arctic)
# Local harness (1-db): formula_1 seed only — no datasets/ clone required for smoke_3
# Full BIRD (AWS / large suites): datasets/minidev/MINIDEV_postgresql/BIRD_dev.sql

.\scripts\local\up-db.ps1
.\scripts\local\load_bird_1db.ps1
.\scripts\local\up-gpu.ps1
.\scripts\local\smoke-db.ps1 -Profile 1db
.\scripts\local\smoke-gpu.ps1

.\scripts\local\up-stack.ps1 -Stack langchain -WithUI -Build
.\scripts\local\smoke-stack.ps1 -Stack langchain
.\scripts\local\run-benchmark.ps1 -Stack langchain -Suite smoke_3 -DbProfile 1db
```

Repeat `up-stack` / `smoke-stack` for: `dbgpt`, `premsql`, `vanna`, `wrenai`, `chat2db`.

**Chat2DB:** after UI smoke, configure Custom AI with `OLLAMA_HOST` manually.

## Phase 2: AWS — persistent volume

```powershell
cd nl2sql-comparison\terraform\persistent
copy terraform.tfvars.example terraform.tfvars
terraform init
terraform apply
# Note volume_id output
```

## Phase 3: AWS — compute

```powershell
cd ..\compute
copy terraform.tfvars.example terraform.tfvars
# Set persistent_volume_id, allowed_ssh_cidr, key_name, bird_dataset_bucket, bird_dataset_version
terraform init
terraform apply
terraform output -json > tf-outputs.json
```

Generate SSH config (optional — deploy/smoke use **SSM**):

```powershell
.\scripts\aws\write-ssh-config.ps1
# Uses aws/credentials/test-pair.pem (key_name=test-pair in terraform.tfvars)
```

## Phase 4–5: BIRD and DB deploy (S3 only — no laptop → EC2 copy)

**Do not** `scp`/`rsync` `BIRD_dev.sql` to the DB host. Flow: laptop → S3 → DB EC2.

```powershell
cd nl2sql-comparison

# One command: upload BIRD + publish package + SSM deploy/load on DB instance
.\scripts\aws\deploy-db-from-s3.ps1

# Or separately:
.\scripts\aws\upload-bird-to-s3.ps1 -ReadBucketFromTfvars -Version 2026-05-24
.\scripts\aws\publish-package-to-s3.ps1 -Version 2026-05-24
.\scripts\aws\deploy-db-from-s3.ps1 -SkipUpload
```

Match `bird_dataset_version` in `terraform/compute/terraform.tfvars`. DB host downloads:

- `s3://<bucket>/nl2sql-comparison/bird/<version>/BIRD_dev.sql`
- `s3://<bucket>/nl2sql-comparison/bird/<version>/package.tgz`

Loader on EC2: `scripts/aws/stage-bird-assets.sh` (called from `ssm-deploy-db-only.sh`).

## Phase 6: Sync package to EC2 (optional)

**Prefer S3 + SSM** (`publish-package-to-s3.ps1` + deploy scripts). SSH tar sync is a dev fallback:

```powershell
.\scripts\aws\write-ssh-config.ps1   # once, uses aws/credentials/test-pair.pem
.\scripts\aws\sync-to-ec2.ps1         # auto-uses ~/.ssh/nl2sql_comparison_ssh_config
```

## Phase 6–7: GPU deploy and NL2SQL smokes (SSM — preferred)

```powershell
cd nl2sql-comparison

# GPU: Ollama + active model on GPU host (allow ~30–60 min first Arctic pull)
.\scripts\aws\deploy-gpu-from-s3.ps1

# Manual model switch (AWS only — not auto-switched by start-stack or orchestrator)
.\scripts\aws\set-gpu-model.ps1 -ModelProfile sql       # Arctic (default)
.\scripts\aws\set-gpu-model.ps1 -ModelProfile general # Qwen for Chat2DB

# One framework: deploy + health smoke on NL2SQL host (remote DB + remote Ollama)
# Chat2DB: run set-gpu-model.ps1 -ModelProfile general first
.\scripts\aws\start-stack.ps1 -Stack langchain

# All six frameworks (sequential; WrenAI is slowest)
.\scripts\aws\smoke-aws-all.ps1
```

`start-stack.ps1` calls `deploy-gpu-from-s3.ps1` then `smoke-aws-stack.ps1` (SSM on NL2SQL EC2).  
Set `compose/.env` on NL2SQL automatically via SSM: `BIRD_PG_HOST=<db private ip>`, `OLLAMA_HOST=http://<gpu private ip>:11434`.

After health checks, `ssm-smoke-stack.sh` runs **NL smoke** for **langchain** and **dbgpt**: `POST /v1/chat` with question `how many tables in db` (up to 15 min, Arctic on GPU). Other stacks log `NL_SMOKE_SKIP` (UI-only). Republish package after stack code changes: `publish-package-to-s3.ps1`.

**Optional SSH** (debug / port-forward; key: `aws/credentials/test-pair.pem`):

```powershell
.\scripts\aws\write-ssh-config.ps1
ssh -F "$env:USERPROFILE\.ssh\nl2sql_comparison_ssh_config" nl2sql-comparison-gpu "docker ps"
ssh -F "$env:USERPROFILE\.ssh\nl2sql_comparison_ssh_config" -L 8011:127.0.0.1:8011 nl2sql-comparison-nl2sql
```

| Use case | Tool |
|----------|------|
| Deploy DB / GPU / stacks, health smokes | **SSM** (`deploy-*-from-s3.ps1`, `start-stack.ps1`) |
| Interactive shell, logs, port-forward | **SSH** + `test-pair.pem` |
| Code sync without S3 round-trip | **SSH** `sync-to-ec2.ps1` |

**Do not** run Ollama on the NL2SQL host in v1 — use the GPU host only.

## Phase 8: Harness experiments (laptop + AWS cluster)

Playwright and EX scoring run on the **laptop**; stacks and Ollama run on EC2. Full runbook: [`EXPERIMENTS.md`](EXPERIMENTS.md).

```powershell
cd nl2sql-comparison
.\scripts\aws\ensure-cluster.ps1
.\scripts\aws\write-ssh-config.ps1

# Probe Arctic latency (smoke_3)
.\scripts\aws\run-benchmark-aws.ps1 -ProbeOnly -SkipPublish

# Full pass (profile: model, suite, stacks)
.\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/arctic-small10-all.json
```

Profiles: `experiments/profiles/*.json`. Commit `results/<run_id>/manifest.json` and `summary.md` only.

## Phase 9: Stop system

```powershell
.\scripts\aws\stop-system.ps1
```

Destroys **compute** EC2 only. Retains `terraform/persistent` EBS and S3 BIRD objects.

## Spot recovery

**Not OK to run NL2SQL smokes without a running GPU** — stacks call `OLLAMA_HOST` on the GPU private IP. Spot termination removes the instance; Terraform state may still list the old instance ID/IP.

Check first:

```powershell
.\scripts\aws\ensure-cluster.ps1
```

If Spot terminates db/gpu/nl2sql:

1. `terraform apply` in `compute/` (re-create instances)
2. Re-sync package if needed
3. DB: EBS reattaches; if `/data/postgres/.bird_loaded` exists, skip `stage-bird-assets.sh`
4. GPU: Ollama re-pulls Arctic (allow time)
5. NL2SQL: `docker compose up -d --build` for active stack

## Health endpoints (v1)

| Stack | URL |
|-------|-----|
| langchain | `http://127.0.0.1:8011/healthz` |
| dbgpt | `http://127.0.0.1:8012/healthz` |
| premsql | Playground UI `http://127.0.0.1:8501` (Streamlit); AgentServer `http://127.0.0.1:8010/health`; Django API `:8000` |
| vanna | `http://127.0.0.1:8001/docs` |
| wrenai | `http://127.0.0.1:3001` |
| chat2db | `http://127.0.0.1:10825/` |
