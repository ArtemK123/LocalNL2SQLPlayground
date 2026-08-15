# Arctic + vLLM resource & deployment metrics (AWS doris-test)

**Campaign report** for article-ready hardware / runtime / ops numbers on the **Doris** primary cluster, collected with the same protocol as [`nl2sql-comparison/experiments/arctic-vllm-resource-metrics-20260810.md`](../../nl2sql-comparison/experiments/arctic-vllm-resource-metrics-20260810.md) (SQLite/Postgres).  
**Related EX report:** [`arctic-vllm-doris-vs-sqlite-postgres.md`](arctic-vllm-doris-vs-sqlite-postgres.md).  
**Source snapshot:** `results/resource_snapshot_20260815/` (SSM metrics + timed start-from-stopped + warm vLLM restart).  
**EX context run (prior, not re-run):** `doris_20260815_113514` (full minidev 500, jsonl latency reused).

**Collection run ID:** `resource_snapshot_20260815`  
**Collected (UTC):** 2026-08-15 09:48–10:09  
**Account / region:** `760366575309` / `us-east-1`  
**Method:** SSM `AWS-RunShellScript` (`nvidia-smi`, `docker stats`, `df`/`du`, timed vLLM restart + short `/v1/completions`) **plus** wall-clock `start-instances` → healthy (not in the Aug 10 SQLite/PG session, which measured an already-running cluster).  
**Bring-up class:** **start-from-stopped** (EBS already has Docker images, HF cache, Doris BE data). **Not** a greenfield `terraform apply` / first-ever S3 deploy.  
**Cluster after collection:** five instances **stopped** (`aws ec2 stop-instances`); compute **not** destroyed.

Labels: **[M]** = measured this session · **[E]** = estimated / documented from prior runs or Terraform defaults · **[D]** = design / ops docs

---

## 1. Hardware footprint

| Role | Instance type | vCPU | RAM | GPU / VRAM | Root EBS | Extra storage | Spot? |
|------|---------------|------|-----|------------|----------|---------------|-------|
| Bastion | `t3.micro` | 2 | 1 GiB | — | 30 GB gp3 | — | on-demand |
| DB | `c7i.xlarge` | 4 | 8 GiB | — | 30 GB gp3 | **50 GB gp3** persistent BIRD (`vol-033ae4a34a5b3e3e6`) | On-demand (`db_use_spot=false`) |
| GPU | `g6.xlarge` | 4 | 16 GiB | **1× NVIDIA L4 / 23034 MiB** (`nvidia-smi`) | **150 GB gp3** (grown from Terraform default 80) | Docker HF volume on root | **On-demand** (`gpu_use_spot=false`) |
| Analytics | `r6i.xlarge` | 4 | 32 GiB | — | 50 GB gp3 | **100 GB gp3** Doris BE (`vol-03a47740bc54d93bb`) | On-demand |
| NL2SQL | `c7i.large` | 2 | 4 GiB | — | 50 GB gp3 | — | On-demand |

**Live instance IDs at collection:** GPU `i-0ad457dd0776fa54f` (`10.60.1.122`), DB `i-0a35e44354091861c` (`10.60.1.47`), analytics `i-0c0f6c2e9fedabf8f` (`10.60.1.222`), NL2SQL `i-0c218394b74115165` (`10.60.1.91`), bastion `i-0e40d60a6e077d034` (`10.60.1.19`).

**Total provisioned block storage (this layout):** 30+30+50+150+50+50+100 = **460 GB gp3** (plus S3). SQLite/PG comparison cluster was **350 GB gp3** (no analytics role; GPU root 160 GB; NL2SQL `c7i.xlarge` / 80 GB).

Sources: `terraform/compute/variables.tf` + `terraform.tfvars`, `aws ec2 describe-instances` / `describe-volumes` / `describe-instance-types` **[M]**.

---

## 2. Measured resource numbers

### 2.1 GPU (vLLM + Arctic) — idle / steady-state **[M]**

Snapshot `ts=2026-08-15T10:03:12Z`, container `StartedAt=2026-08-15T09:59:28Z` (~4 min, healthy).

| Metric | Value | Notes |
|--------|-------|-------|
| GPU | NVIDIA L4 | |
| VRAM total | 23034 MiB | `nvidia-smi` |
| VRAM used (idle, model loaded) | **21358 MiB (~92.7%)** | Process `VLLM::EngineCore` 21350 MiB |
| GPU util (idle) | **0%** | |
| Mem util (idle) | **0%** | |
| Power (idle) | **~27.4–27.5 W** | |
| Host RAM | 15365 MiB total; ~3627 MiB used; ~11 GiB available | |
| Host load | 0.42 / 0.44 / 0.20 (1/5/15) | 4 vCPU |
| Root disk | **150G, 57G used (38%)** | |
| `vllm/vllm-openai:latest` image | **21.4 GB** | Aug 10 comparison snapshot was 18.9 GB |
| HF cache volume | **15.25 GB** (`doris-test-gpu-vllm_vllm_hf_cache`); `du` **14.2G** `/cache` | Arctic weights + HF assets |
| vLLM container RSS | **3.67 GiB / 15 GiB** (24.4% of host limit) | `docker stats` |
| Container CPU (idle) | **~1.29%** | |
| `/v1/models` | Serving `Snowflake/Arctic-Text2SQL-R1-7B`, `max_model_len=4096` | healthy |

Config knobs (compose): `--gpu-memory-utilization 0.90`, `--max-model-len 4096`, `--enable-prefix-caching`, dtype `auto` **[D]**.

SQLite/PG Aug 10 idle VRAM was **20848 MiB (~90.5%)** on the same L4 class; this session is ~0.5 GiB higher with a newer `vllm` image.

### 2.2 GPU — under short inference **[M]**

Timed `POST /v1/completions` (1 prompt token → 48 completion tokens, `temperature=0`), concurrent ~0.25 s `nvidia-smi` sampling, `ts≈2026-08-15T10:04:04Z`.

| Metric | Value |
|--------|-------|
| Client latency | **2728 ms** |
| Peak GPU util | **100%** |
| Peak mem util | **100%** |
| Peak power | **~72.7 W** |
| VRAM during infer | **21358 MiB** (flat — KV preallocated; no further climb on this short request) |

Aug 10 comparison probe: **2442 ms**, peak util/mem **100%**, peak power **~72.4 W**, VRAM flat at 20848 MiB.

**Interpretation (same as Aug 10):** With `gpu-memory-utilization=0.90`, VRAM is largely reserved at load; “peak” for article purposes is the **prealloc steady footprint (~21.4 GiB this session)**, not a large dynamic spike. Utilization and power are the dynamic signals.

### 2.3 GPU — warm restart / model reload **[M]**

`docker compose restart vllm` with HF cache already on disk:

| Phase | Time (UTC) | Duration |
|-------|------------|----------|
| Restart issued | 10:04:44Z | T0 |
| Container started | 10:04:45Z | ~1 s |
| Weights loaded | 10:06:34Z | **85.16 s** weight I/O |
| Model loading total | — | **86.71 s**, **14.29 GiB** weights in VRAM |
| Engine init (profile/KV/warmup) | — | **14.82 s** (compile 0.14 s) |
| `Application startup complete` / `/v1/models` ready | 10:06:50–10:06:52Z | **warm_restart_ready_sec = 128** |

Post-restart `nvidia-smi`: **21358 MiB** used, util 0%, ~27.4 W.  
vLLM reports GPU KV cache **5.04 GiB** / **94,320 tokens** ≈ **23.0×** max concurrency at 4096 tokens/req. Weight 14.29 GiB + KV + activations/graphs fit under 0.90 of ~22 GiB.

**Start-from-stopped model load (this session, not compose-restart) [M]:** container `StartedAt=09:59:28Z` → startup complete `10:02:21Z` = **173 s**. Weight I/O **115.72 s**, model loading **117.30 s** / 14.29 GiB, engine init **18.06 s** (compile 0.28 s).

**Cold deploy (documented, not re-timed this session) [E/D]:** first `deploy-gpu-vllm-from-s3.ps1` waits up to ~60 min (`TimeoutSec=7200`); SSM script comments HF download + load can take **10–30+ min** on a cold host. This session used cached `vllm` image + HF volume (no S3 GPU redeploy).

### 2.4 DB host **[M]** (`ts=2026-08-15T10:03:13Z`)

| Metric | Value |
|--------|-------|
| Type | `c7i.xlarge` |
| RAM used | ~288 MiB / 7783 MiB |
| Root disk | 30G, **7.2G used (25%)** |
| BIRD data dir | `du` **2.0G** `/data/postgres` (same as Aug 10) |
| Persistent 50 GB EBS | **attached** (`nvme1n1`) but **not mounted** this boot — see caveats |
| Postgres container | `postgres:16-alpine` (~294 MB image); **~50 MiB** RSS idle; CPU ~0% |
| Tables (non-system) | **75** in **13** schemas |
| Load | 0.03 / 0.14 / 0.08 |

Aug 10 comparison (post-campaign): Postgres RSS **~1.04 GiB**, root 4.3G used, 50 GB volume **mounted** (2.4G used). This session is idle start-from-stopped.

### 2.5 Analytics host **[M]** (`ts=2026-08-15T10:03:13Z`) — Doris-only role

| Metric | Value |
|--------|-------|
| Type | `r6i.xlarge` |
| RAM used | ~3878 MiB / 31561 MiB |
| Root disk | 50G, **23G used (45%)** |
| Doris BE EBS | 100G, **1.3G used (2%)** `/data/doris-be` |
| Kafka volume | **12.51 GB** (`doris-test-analytics_kafka_data`) |
| FE meta volume | 15.5 MB |
| Images | FE 1.99 GB, BE 5.44 GB, Debezium connect 1.4 GB, Kafka 655 MB |
| Container RSS | FE **1021 MiB** (CPU ~24%); BE **997 MiB** (CPU ~24%); Kafka **1.18 GiB**; Connect **554 MiB** |
| ODS probe | `formula_1.races` **1908**; `california_schools.schools` **35372**; FE/BE `Alive: true` |

CPU at snapshot is still settling after FE/BE come up (~11 min up); not a sustained query-load sample.

### 2.6 NL2SQL host **[M]** (`ts=2026-08-15T10:09:23Z`)

| Metric | Value |
|--------|-------|
| Type | `c7i.large` (comparison cluster used `c7i.xlarge`) |
| RAM used | ~381 MiB / 3819 MiB |
| Root disk | 50G, **5.0G used (10%)** |
| Active stack | Langchain API only (`doris-test-langchain-langchain-api-1`, healthy) |
| API image | ~383 MB |
| Container RSS | **~142 MiB**; CPU ~0.17% |
| Health | `GET :8011/healthz` → `{"status":"ok"}` (`NL2SQL_SMOKE_OK backend=vllm db=doris`) |
| Docker images | several stale 381–383 MB builds |

### 2.7 Object storage (S3) **[M]**

Bucket `doris-test-bird-760366575309`, prefix `doris-test/package/`:

| Object class | Size |
|--------------|------|
| `2026-08-10/BIRD_dev.sql` | **955.5 MiB** |
| `package.tgz` versions | ~4.6–4.7 MiB each (2026-08-10/14/15) |
| Prefix total (listed) | **~969.6 MiB** |

### 2.8 Harness EX / latency context (prior scored run) **[E]** from jsonl, not a live 500 re-run

Protocol on SQLite/PG reported **median latency_ms** and wall clock from scored campaigns. Same fields here from `doris_20260815_113514` (`jsonl/langchain_full.jsonl`, n=500, workers=2, timeout 10 s, one-pass).

| Run | Config | Headline EX | Wall | Latency |
|-----|--------|-------------|------|---------|
| `doris_20260815_113514` | study-parity Doris dual-DSN, 10s, w=2 | overall **0.42** (210/500); dual_ok **0.468** (210/449) | **~27 min** (jsonl dir 11:35 → last write 12:02 local / 08:35–09:02 UTC) | **mean 3839 ms · median/p50 3424 ms · p95 7213 ms** (all 500); api_ok n=488 mean 3710 / median 3407 / p95 6474 |
| Aug 9 SQLite `aws_20260809_studyparity_full` | same-engine, 10s, w=2 | Strict **0.536** | ~17.5 min | median **3328 ms** |
| Aug 9 Postgres `aws_20260809_studyparity_postgres` | same-engine, 10s, w=2 | Strict **0.420** | ~24 min | median ~3.3 s |
| Aug 9 one-pass PG `aws_20260809_onepass10s_full_r2` | 10s, w=2 | Strict **0.320** | ~25.5 min | median **3276 ms** |

p50 equals median on this jsonl (integer milliseconds). Aug 10 resource note used **median**, not p95; p95 is extra for the article.

vLLM engine logs retained from that 500-run (before this session’s compose restart) **[E]:** prompt throughput typically **~110–280 tokens/s**, generation **~15–25 tokens/s**, GPU KV cache **0–2.5%**, prefix-cache hit **~55%**, running 1–2 reqs (matches workers=2). Not a separate live smoke of N questions.

Harness flag `--resources none` on AWS (no local Docker resource series in manifests) **[D]**.

---

## 3. Startup timeline

**This session is start-from-stopped.** GPU was started **last**, after Doris ODS healthy (cost rule). Full analytics S3 CDC deploy (30–90 min) was **not** repeated; compose brought back existing containers.

| Phase | Typical time | Source |
|-------|--------------|--------|
| Terraform apply / EC2 pending→running (warm AZ) | **~2–5 min** [E] | Aug 10 note; **not** this session |
| `start-instances` db + analytics + bastion → `running` | **~seconds** [M] | issued 09:48:38Z; LaunchTime 09:48:38Z |
| SSM agent Online | **~12 s** [M] | LastPing 09:48:50Z |
| DB: Postgres up + BIRD already on disk | **~2.9 min** from start-instances [M] | `pg_isready` + `california_schools.schools` 17686 at ~09:51:30Z |
| Analytics: compose up → FE/BE healthy + ODS counts | **8 min 14 s** from start-instances [M] | ODS_HEALTHY 09:56:52Z; races 1908 |
| GPU: `start-instances` → `running` + SSM | **~14 s** [M] | issued 09:57:30Z |
| GPU: **start-from-stopped** container start → `/v1/models` | **173 s** load; **~5.1 min** including instance boot [M] | StartedAt 09:59:28Z; ready 10:02:21–10:02:34Z |
| GPU: **warm** `compose restart` → `/v1/models` | **128 s** [M] | this session (Aug 10 was **122 s**) |
| ↳ of which weight load (restart) | **~85 s** [M] | Aug 10 **~76 s** |
| ↳ of which engine init (restart) | **~15 s** [M] | Aug 10 **~20 s** |
| GPU: pull vLLM image (cold) | **tens of minutes** if not cached [E] | ~21 GB image |
| GPU: HF Arctic download (cold) | **10–30+ min** [D] | `ssm-deploy-gpu-vllm.sh` |
| Analytics: full `deploy-analytics-from-s3.ps1` (CDC + routine loads) | **30–90 min** [D] | `AI_OPERATIONS.md`; **not** re-timed |
| NL2SQL: `deploy-nl2sql-from-s3.ps1 -SkipPublish` (image cached) | **37 s** to healthz [M] | 10:08:14–10:08:51Z; S3 `package.tgz` 4.7 MiB + cached build |
| First inference after ready (tiny prompt) | **~2.7 s** [M] | |
| Steady NL2SQL question latency (Doris 500q) | **median 3.42 s** [E] | `doris_20260815_113514` |
| Full 500q wall (one-pass w=2, dual-DSN laptop score) | **~27 min** [E] | jsonl mtimes |

**Cold vs warm (article wording):**

- **Cold GPU host:** image + HF pull dominate (order **tens of minutes**). Not measured this session.
- **Warm GPU (cache on 150 GB root, stop/start instances):** model reload **~3 min** (173 s) after the container starts; instance boot + compose add ~2 min → **~5 min** GPU start → API ready.
- **Warm GPU compose restart (HF already loaded once this boot):** **128 s** to API ready (Aug 10 SQLite/PG: **122 s**).
- **Start-from-stopped analytics:** FE/BE + ODS **~8 min** after db+analytics start. **Not** the 30–90 min greenfield CDC snapshot.
- **`stop-system.ps1` (terraform destroy):** next bring-up is closer to cold for compute; persistent 50 GB PG + 100 GB Doris BE EBS + S3 retained. **This collection used stop-instances, not destroy.**

**End-to-end this session (GPU last):** db/analytics start 09:48:38Z → NL2SQL healthz 10:08:51Z = **20 min 13 s** wall, of which ~9 min is waiting for ODS before starting the GPU.

---

## 4. Ops section (grounded in repo scripts/docs)

### Maintenance complexity — **moderate, scripted, single-tenant, extra analytics hop**

- **One NL2SQL stack at a time** on the NL2SQL host.
- **GPU backend:** vLLM path (`deploy-gpu-vllm-from-s3.ps1`) on port **11434** (Ollama mutually exclusive).
- **Fourth role (analytics):** Kafka + Debezium + Doris FE/BE; ODS health is a gate before GPU (cost) and before scoring.
- **Scoring host:** laptop tunnels (PG `:55433` + Doris `:9031`) or analytics — **not** nl2sql under default SG.
- **Spot:** all roles on-demand in current `terraform.tfvars` (comparison cluster used Spot for DB/NL2SQL).
- **Package updates:** `publish-package-to-s3.ps1` then SSM deploy; this session used `-SkipPublish` / existing `2026-08-10` prefix objects.
- **Disk ops:** GPU root **150 GB** (comparison used 160 GB); analytics BE on 100 GB gp3.

### Monitoring strategy — **what exists today**

Same as Aug 10 comparison cluster: compose healthchecks, `/v1/models`, stack `/healthz`, ad-hoc SSM `nvidia-smi`, harness JSONL. No CloudWatch dashboards wired in-repo **[D]**.

### Operational overhead (long-term)

| Activity | Overhead |
|----------|----------|
| Idle cost control | **High impact** — stop GPU (`g6.xlarge`) and analytics (`r6i.xlarge`) when idle; this collection used `aws ec2 stop-instances` |
| Experiment day | Laptop harness + SSM tunnels; dual-DSN scoring adds laptop/tunnel wall vs same-engine SQLite |
| Spot recovery | Not used on this cluster currently |
| Data plane | BIRD via S3; 50 GB PG + 100 GB BE EBS survive destroy |
| Start-from-stopped mount | fstab/user_data does **not** always remount PG EBS (observed this boot) |

---

## 5. Feasibility by enterprise tier

| Tier | Fit | Notes |
|------|-----|------|
| **Single GPU workstation** (1× L4/A10 24 GB, 16+ GB RAM, ≥150 GB free disk) | **Feasible** for Langchain API + vLLM Arctic | Still need Postgres + BIRD (~2 GB) **and** Doris FE/BE + Kafka if reproducing the analytics path |
| **Cloud small (this cluster: g6.xlarge + c7i.xlarge + r6i.xlarge + c7i.large)** | **Validated** | overall EX 0.42 on dual-DSN 500; median ~3.4 s; VRAM ~21.4 GiB reserved |
| **g5.xlarge fallback** | Documented alternative when g6 capacity missing | Same 24 GB-class A10G |
| **Multi-tenant / shared GPU** | Needs extra work | Full VRAM prealloc (0.90) poor for co-tenancy |
| **Larger GPU (g6.2xlarge / A100)** | Headroom for longer context or higher concurrency | Current max concurrency ~23× at 4k |

**Bottom line for article:** A **single L4 24 GB** with ~**21.4 GiB** steady VRAM reservation, **~21 GB** container image, **~15 GB** HF cache, **~2 GB** BIRD Postgres data, plus an **r6i.xlarge** analytics host (Doris FE/BE + Kafka) is sufficient to serve Arctic Text2SQL R1-7B and score full BIRD minidev (500) in **~27 minutes** wall under the one-pass 10s dual-DSN configuration. **Start-from-stopped** (images on EBS) brings ODS + vLLM + API to healthy in **~20 minutes** with GPU started last; **greenfield** analytics CDC remains **30–90 minutes** and was not re-timed.

---

## 6. Cluster stop confirmation

After metrics collection, `aws ec2 stop-instances` was issued at **2026-08-15T10:12:12Z** for all five roles (not `stop-system.ps1` / terraform destroy). All five **stopped** as of 2026-08-15T10:26Z.

| Check | Result |
|-------|--------|
| DB `i-0a35e44354091861c` | **stopped** |
| Analytics `i-0c0f6c2e9fedabf8f` | **stopped** |
| NL2SQL `i-0c218394b74115165` | **stopped** |
| Bastion `i-0e40d60a6e077d034` | **stopped** |
| GPU `i-0ad457dd0776fa54f` | **stopped** |
| Persistent PG EBS `vol-033ae4a34a5b3e3e6` | **retained** (50 GB) |
| Persistent Doris BE EBS `vol-03a47740bc54d93bb` | **retained** (100 GB) |
| S3 package/BIRD objects | **retained** (~970 MiB) |

---

## 7. Artifact paths

| Path | Contents |
|------|----------|
| `doris-test/experiments/arctic-vllm-doris-deploy-runtime-metrics.md` | This note |
| `doris-test/results/resource_snapshot_20260815/` | SSM captures (warm restart logs, DB extra) |
| `doris-test/experiments/arctic-vllm-doris-vs-sqlite-postgres.md` | EX comparison vs SQLite/PG |
| `nl2sql-comparison/experiments/arctic-vllm-resource-metrics-20260810.md` | Prior protocol (SQLite/PG) |
| `doris-test/results/doris_20260815_113514/` | Scored 500-run manifest + jsonl latency |
| `doris-test/compose/docker-compose.gpu.vllm.yml` | Serve knobs |

Temporary SSM helper scripts: `scripts/aws/_tmp_wait_ods.sh`, `_tmp_collect_host.sh`, `_tmp_collect_gpu_idle.sh`, `_tmp_collect_infer_peak.sh`, `_tmp_warm_restart_vllm.sh`, `_tmp_extract_vllm_startup.sh`, `_tmp_collect_db_extra.sh`.

---

## 8. Caveats (do not mix with greenfield)

1. **Start-from-stopped, not terraform apply.** Docker images, HF cache, and Doris BE data were already on EBS. Cold GPU HF download and analytics CDC snapshot were **not** re-measured; cite Aug 10 / `AI_OPERATIONS.md` for those **[E/D]**.
2. **GPU last.** ODS was healthy before `g6.xlarge` started. End-to-end ~20 min includes ~9 min of GPU-off wait; parallel start would shorten wall and raise cost.
3. **No live 500 re-run.** Latency p50/p95/mean and ~27 min wall come from existing `doris_20260815_113514` jsonl / file mtimes. Live GPU samples are idle + one tiny completion + compose restart.
4. **NL2SQL S3 deploy was warm.** `package.tgz` pull + **cached** Docker build; 37 s is not a first-ever image build.
5. **PG 50 GB volume not mounted this boot.** `nvme1n1` attached, `findmnt /data/postgres` empty; `du` 2.0G lives on the root filesystem bind-mount. Postgres still served 75 tables / 17686 schools. Do not claim the persistent volume was active this session.
6. **Footprint differs from the 3-role comparison cluster:** extra `r6i.xlarge` + 100 GB BE; GPU root 150 vs 160 GB; NL2SQL `c7i.large` / 4 GiB vs `c7i.xlarge` / 8 GiB; vLLM image 21.4 vs 18.9 GB.
7. **Short inference prompt** was 1→48 tokens (Aug 10 used 19→43). Dynamic signals (100% util, ~73 W, flat VRAM) still match; client latency 2728 vs 2442 ms is the same order, not a matched TTFT study.
