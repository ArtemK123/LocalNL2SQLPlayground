#!/bin/bash
# Run doris-test harness on an EC2 host that can reach BOTH gold PG and Doris.
#
# Preferred SCORE_HOST values:
#   laptop    — do not use this script; use run-benchmark-aws.ps1 + SSH tunnels
#   analytics — this host can reach Doris :9030 and (by SG) PG :5432
#   nl2sql    — BLOCKED by default (SG does not allow nl2sql→db:5432)
#
# Override only when you have opened SG or tunnelled gold:
#   ALLOW_NL2SQL_GOLD_SCORE=1
set -euo pipefail

SCORE_HOST="${SCORE_HOST:-}"
ALLOW_NL2SQL_GOLD_SCORE="${ALLOW_NL2SQL_GOLD_SCORE:-0}"
BUCKET="${PACKAGE_BUCKET:-}"
PREFIX="${PACKAGE_PREFIX:-doris-test/package}"
VERSION="${PACKAGE_VERSION:-}"
RUN_ID="${RUN_ID:?RUN_ID required}"
SUITE="${SUITE:-minidev_diverse_10}"
EVAL_MODE="${EVAL_MODE:-dual_dsn}"
WORKERS="${WORKERS:-2}"
TIMEOUT_SEC="${TIMEOUT_SEC:-10}"
API_URL="${API_URL:-http://127.0.0.1:8011/v1/chat}"
# Defaults assume analytics private networking (NOT nl2sql).
GOLD_DSN="${GOLD_DSN:-postgresql://olap:olap@${BIRD_PG_HOST:-10.60.1.241}:5432/bird}"
PRED_DSN="${PRED_DSN:-mysql://root@127.0.0.1:9030/bird_minidev_olap}"
JUDGE_BASE_URL="${JUDGE_BASE_URL:-}"
JUDGE_MODEL="${JUDGE_MODEL:-Snowflake/Arctic-Text2SQL-R1-7B}"

detect_role() {
  if [ -n "${SCORE_HOST}" ]; then
    echo "${SCORE_HOST}"
    return
  fi
  # Heuristic: Doris FE local → analytics; else nl2sql/other.
  if curl -sf --connect-timeout 1 "http://127.0.0.1:8030/api/bootstrap" >/dev/null 2>&1 \
     || ss -lnt 2>/dev/null | grep -q ':9030'; then
    echo "analytics"
  else
    echo "nl2sql"
  fi
}

ROLE="$(detect_role)"
echo "SCORE_HOST_ROLE=${ROLE}"

if [ "${ROLE}" = "nl2sql" ] && [ "${ALLOW_NL2SQL_GOLD_SCORE}" != "1" ]; then
  cat >&2 <<'EOF'
REFUSING to score gold PostgreSQL from nl2sql host.

Security group blocks nl2sql → db:5432. Running dual_dsn here yields gold
connection timeouts and EX=0 with soft_f1=0 (misleading).

Use one of:
  1) Laptop tunnels (preferred):
       .\scripts\aws\write-ssh-config.ps1
       .\scripts\aws\preflight-eval-health.ps1
       .\scripts\aws\run-benchmark-aws.ps1 -Profile experiments/profiles/...
     gold_dsn=postgresql://...@127.0.0.1:55433/bird
     pred_dsn=mysql://...@127.0.0.1:9031/bird_minidev_olap
  2) Run this script on analytics (SCORE_HOST=analytics) where SG allows PG+Doris.
  3) Explicit override after opening SG / bastion tunnel:
       ALLOW_NL2SQL_GOLD_SCORE=1
EOF
  exit 3
fi

if [ -z "${BUCKET}" ] || [ -z "${VERSION}" ]; then
  echo "PACKAGE_BUCKET and PACKAGE_VERSION required unless harness already present" >&2
fi

if [ ! -d /home/ec2-user/doris-test/harness ]; then
  aws s3 cp "s3://${BUCKET}/${PREFIX}/${VERSION}/package.tgz" /tmp/doris-test.tgz
  mkdir -p /home/ec2-user/doris-test
  tar -xzf /tmp/doris-test.tgz -C /home/ec2-user/doris-test
fi

dnf install -y python3.11 python3.11-pip python3.11-devel gcc 2>/dev/null \
  || dnf install -y python3 python3-pip python3-devel gcc || true
PY=python3.11
command -v python3.11 >/dev/null || PY=python3
$PY -m pip install -U pip -q
cd /home/ec2-user/doris-test/harness
$PY -m pip install -e . -q

# Optional health gate (Doris local on analytics).
export PRED_DSN GOLD_DSN
if [ -f /home/ec2-user/doris-test/scripts/aws/preflight-eval-health.sh ]; then
  bash /home/ec2-user/doris-test/scripts/aws/preflight-eval-health.sh || {
    echo "preflight-eval-health failed" >&2
    exit 4
  }
fi

OUT_DIR="/home/ec2-user/doris-test/results/${RUN_ID}"
mkdir -p "${OUT_DIR}/jsonl"
OUT_JSONL="${OUT_DIR}/jsonl/langchain_${SUITE}.jsonl"

ARGS=(
  run-api
  --suite "${SUITE}"
  --api-url "${API_URL}"
  --eval-mode "${EVAL_MODE}"
  --timeout "${TIMEOUT_SEC}"
  --workers "${WORKERS}"
  --out "${OUT_JSONL}"
  --gold-dsn "${GOLD_DSN}"
  --pred-dsn "${PRED_DSN}"
)
if [ "${EVAL_MODE}" = "dual_dsn_llm_judge" ] || [ "${EVAL_MODE}" = "judge_equiv" ]; then
  if [ -z "${JUDGE_BASE_URL}" ]; then
    echo "JUDGE_BASE_URL required for ${EVAL_MODE}" >&2
    exit 2
  fi
  ARGS+=(--judge-base-url "${JUDGE_BASE_URL}" --judge-model "${JUDGE_MODEL}")
fi

echo "=== HARNESS START run_id=${RUN_ID} eval_mode=${EVAL_MODE} role=${ROLE} ==="
set +e
$PY -m doris_test_harness "${ARGS[@]}"
HC=$?
set -e
echo "=== HARNESS EXIT=${HC} ==="

$PY - <<PY
import json, pathlib, statistics
out = pathlib.Path("${OUT_JSONL}")
rows=[]
if out.exists():
    for line in out.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
n=len(rows)
dual=[r for r in rows if r.get("dual_ok")]
ex=sum(1 for r in dual if r.get("ex") is True)
f1=[float(r["soft_f1"]) for r in dual if r.get("soft_f1") is not None]
lat=[float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]
judged=[r for r in dual if r.get("llm_equivalent") is not None]
eq=sum(1 for r in judged if r.get("llm_equivalent") is True)
summary={
  "run_id":"${RUN_ID}",
  "suite":"${SUITE}",
  "eval_mode":"${EVAL_MODE}",
  "score_host_role":"${ROLE}",
  "n":n,
  "n_api_ok": sum(1 for r in rows if r.get("api_ok")),
  "n_gold_ok": sum(1 for r in rows if r.get("gold_ok")),
  "n_pred_ok": sum(1 for r in rows if r.get("pred_ok")),
  "n_dual_ok": len(dual),
  "ex_among_dual_ok": (ex/len(dual) if dual else None),
  "ex_over_all": (ex/n if n else 0.0),
  "soft_f1_mean_among_dual_ok": (statistics.mean(f1) if f1 else None),
  "latency_ms_mean": (statistics.mean(lat) if lat else None),
  "llm_equiv_rate_among_judged": (eq/len(judged) if judged else None),
  "harness_exit": ${HC},
  "gold_dsn":"${GOLD_DSN}".replace("://olap:olap@","://***@"),
  "pred_dsn":"${PRED_DSN}".replace("://root@","://***@") if False else "${PRED_DSN}",
  "api_url":"${API_URL}",
}
path=pathlib.Path("${OUT_DIR}")
(path/"manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
md=["# ${RUN_ID}", f"- n={n}", f"- n_dual_ok={len(dual)}",
    f"- EX among dual_ok={summary['ex_among_dual_ok']}",
    f"- soft_f1_mean among dual_ok={summary['soft_f1_mean_among_dual_ok']}",
    f"- llm_equiv among judged={summary['llm_equiv_rate_among_judged']}",
    f"- harness_exit=${HC}", f"- score_host_role=${ROLE}"]
(path/"summary.md").write_text("\\n".join(md)+"\\n", encoding="utf-8")
print("\\n".join(md))
print("MANIFEST", json.dumps(summary))
PY
