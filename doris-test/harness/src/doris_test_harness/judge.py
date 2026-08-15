"""LLM-as-judge logical equivalence for cross-engine (PG gold ↔ Doris pred) results.

Reproducibility knobs (persist all of these on every judged record):
  - JUDGE_PROMPT_VERSION
  - judge model id
  - temperature=0
  - canonical row serialization (sort + typed stringify + row/col caps)
  - sha256 of (question, gold_sql, pred_sql, serialized gold/pred tables)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional
from urllib import error, request

from doris_test_harness.db import normalize_value

JUDGE_PROMPT_VERSION = "judge_equiv_v1"
JUDGE_TEMPERATURE = 0.0
DEFAULT_JUDGE_MAX_ROWS = 50
DEFAULT_JUDGE_MAX_COLS = 32
DEFAULT_JUDGE_MAX_CELL_CHARS = 120

_JUDGE_JSON_RE = re.compile(r"\{[\s\S]*\}")

JUDGE_SYSTEM = (
    "You are a deterministic SQL result equivalence judge for NL2SQL benchmarks.\n"
    "Compare GOLD (PostgreSQL) and PRED (often Apache Doris/MySQL) tabular results.\n"
    "Decide whether they are logically equivalent answers to the question, allowing for:\n"
    "- column name/alias differences and column order\n"
    "- row order differences unless the question implies ranking/top-k order\n"
    "- numeric formatting (1 vs 1.0), NULL vs empty string when semantically empty\n"
    "- timestamp formatting without timezone shifts\n"
    "Do NOT treat unrelated values as equivalent. If unsure, set equivalent=false "
    "and confidence low.\n"
    "Respond with ONLY a single JSON object matching the schema."
)

JUDGE_USER_TEMPLATE = """\
Prompt version: {prompt_version}

Question:
{question}

Evidence (optional):
{evidence}

Gold SQL:
{gold_sql}

Pred SQL:
{pred_sql}

GOLD result (canonical JSON; rows sorted; capped):
{gold_table}

PRED result (canonical JSON; rows sorted; capped):
{pred_table}

Return JSON schema:
{{
  "equivalent": bool,
  "confidence": float,   // 0..1
  "rationale": string,   // short
  "mismatch_kind": string | null
    // one of: null, value_mismatch, missing_rows, extra_rows, schema_mismatch,
    //         order_sensitive, abstain, other
}}
"""


@dataclass(frozen=True)
class JudgeVerdict:
    equivalent: bool
    confidence: float
    rationale: str
    mismatch_kind: str | None = None
    abstained: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _typed_stringify(v: Any) -> str:
    n = normalize_value(v)
    if n is None:
        return "NULL"
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, int):
        return f"i:{n}"
    if isinstance(n, float):
        # Stable float rendering for judge inputs.
        return f"f:{n:.12g}"
    s = str(n)
    if len(s) > DEFAULT_JUDGE_MAX_CELL_CHARS:
        s = s[: DEFAULT_JUDGE_MAX_CELL_CHARS - 3] + "..."
    return f"s:{s}"


def canonicalize_table(
    rows: list[dict[str, Any]],
    *,
    max_rows: int = DEFAULT_JUDGE_MAX_ROWS,
    max_cols: int = DEFAULT_JUDGE_MAX_COLS,
) -> dict[str, Any]:
    """Deterministic table serialization for the judge prompt + input hash."""
    if not rows:
        return {"columns": [], "rows": [], "n_rows_total": 0, "truncated": False}

    # Deterministic column order (sorted) so serialization is independent of row order.
    all_cols = sorted({k for r in rows for k in r.keys()})
    cols = all_cols[:max_cols]
    truncated = len(rows) > max_rows or len(all_cols) > max_cols

    serialized_rows: list[list[str]] = []
    for row in rows:
        serialized_rows.append([_typed_stringify(row.get(c)) for c in cols])
    # Canonical multiset order (independent of engine row order).
    serialized_rows.sort(key=lambda r: tuple(r))
    serialized_rows = serialized_rows[:max_rows]

    return {
        "columns": cols,
        "rows": serialized_rows,
        "n_rows_total": len(rows),
        "truncated": truncated,
    }


def inputs_hash(
    *,
    question: str,
    gold_sql: str,
    pred_sql: str,
    gold_table: dict[str, Any],
    pred_table: dict[str, Any],
    evidence: str | None = None,
    prompt_version: str = JUDGE_PROMPT_VERSION,
) -> str:
    payload = {
        "prompt_version": prompt_version,
        "question": question,
        "evidence": evidence or "",
        "gold_sql": gold_sql,
        "pred_sql": pred_sql,
        "gold_table": gold_table,
        "pred_table": pred_table,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_judge_messages(
    *,
    question: str,
    gold_sql: str,
    pred_sql: str,
    gold_table: dict[str, Any],
    pred_table: dict[str, Any],
    evidence: str | None = None,
) -> list[dict[str, str]]:
    user = JUDGE_USER_TEMPLATE.format(
        prompt_version=JUDGE_PROMPT_VERSION,
        question=question,
        evidence=(evidence or "").strip() or "(none)",
        gold_sql=gold_sql,
        pred_sql=pred_sql,
        gold_table=json.dumps(gold_table, ensure_ascii=False, indent=2),
        pred_table=json.dumps(pred_table, ensure_ascii=False, indent=2),
    )
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": user},
    ]


def _parse_verdict(raw: str) -> JudgeVerdict:
    text = (raw or "").strip()
    m = _JUDGE_JSON_RE.search(text)
    if not m:
        return JudgeVerdict(
            equivalent=False,
            confidence=0.0,
            rationale="judge_parse_error: no JSON object",
            mismatch_kind="abstain",
            abstained=True,
        )
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return JudgeVerdict(
            equivalent=False,
            confidence=0.0,
            rationale=f"judge_parse_error: {exc}",
            mismatch_kind="abstain",
            abstained=True,
        )
    equiv = bool(obj.get("equivalent", False))
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    rationale = str(obj.get("rationale") or "")[:1000]
    kind = obj.get("mismatch_kind")
    kind_s = str(kind) if kind is not None else None
    abstained = kind_s == "abstain"
    return JudgeVerdict(
        equivalent=equiv and not abstained,
        confidence=conf,
        rationale=rationale,
        mismatch_kind=kind_s,
        abstained=abstained,
    )


def should_abstain_asymmetric(
    gold_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    *,
    max_rows: int = DEFAULT_JUDGE_MAX_ROWS,
) -> str | None:
    """Return abstain reason, or None if judging is allowed."""
    g_empty, p_empty = (not gold_rows), (not pred_rows)
    if g_empty != p_empty:
        return "asymmetric_empty"
    if len(gold_rows) > max_rows * 20 or len(pred_rows) > max_rows * 20:
        # Extremely large; even after truncate, judge is unreliable.
        return "too_large"
    return None


def call_openai_compatible_judge(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    api_key: str = "EMPTY",
    timeout_s: float = 60.0,
) -> str:
    """POST /v1/chat/completions (OpenAI-compatible; works with vLLM)."""
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    url = f"{base}/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "temperature": JUDGE_TEMPERATURE,
            "messages": messages,
            "max_tokens": 400,
        }
    ).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"judge_http_{exc.code}: {detail}") from exc
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("judge_empty_choices")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", part)) if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "")


JudgeFn = Callable[[list[dict[str, str]]], str]


def judge_equivalence(
    *,
    question: str,
    gold_sql: str,
    pred_sql: str,
    gold_rows: list[dict[str, Any]],
    pred_rows: list[dict[str, Any]],
    evidence: str | None = None,
    judge_fn: Optional[JudgeFn] = None,
    judge_base_url: str | None = None,
    judge_model: str | None = None,
    judge_api_key: str = "EMPTY",
    max_rows: int = DEFAULT_JUDGE_MAX_ROWS,
    timeout_s: float = 60.0,
) -> tuple[JudgeVerdict, dict[str, Any]]:
    """Return (verdict, meta). Meta always includes prompt version + inputs hash."""
    gold_table = canonicalize_table(gold_rows, max_rows=max_rows)
    pred_table = canonicalize_table(pred_rows, max_rows=max_rows)
    ih = inputs_hash(
        question=question,
        gold_sql=gold_sql,
        pred_sql=pred_sql,
        gold_table=gold_table,
        pred_table=pred_table,
        evidence=evidence,
    )
    meta: dict[str, Any] = {
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "judge_temperature": JUDGE_TEMPERATURE,
        "judge_model": judge_model,
        "judge_max_rows": max_rows,
        "judge_inputs_hash": ih,
        "gold_table_meta": {
            "n_rows_total": gold_table["n_rows_total"],
            "truncated": gold_table["truncated"],
            "n_cols": len(gold_table["columns"]),
        },
        "pred_table_meta": {
            "n_rows_total": pred_table["n_rows_total"],
            "truncated": pred_table["truncated"],
            "n_cols": len(pred_table["columns"]),
        },
    }

    abstain = should_abstain_asymmetric(gold_rows, pred_rows, max_rows=max_rows)
    if abstain:
        verdict = JudgeVerdict(
            equivalent=False,
            confidence=0.0,
            rationale=f"abstain:{abstain}",
            mismatch_kind="abstain",
            abstained=True,
        )
        meta["judge_abstain"] = abstain
        return verdict, meta

    messages = build_judge_messages(
        question=question,
        gold_sql=gold_sql,
        pred_sql=pred_sql,
        gold_table=gold_table,
        pred_table=pred_table,
        evidence=evidence,
    )
    meta["judge_messages_sha256"] = hashlib.sha256(
        json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    if judge_fn is None:
        if not judge_base_url or not judge_model:
            raise ValueError("judge_base_url and judge_model required (or pass judge_fn)")
        raw = call_openai_compatible_judge(
            base_url=judge_base_url,
            model=judge_model,
            messages=messages,
            api_key=judge_api_key,
            timeout_s=timeout_s,
        )
    else:
        raw = judge_fn(messages)

    meta["judge_raw"] = (raw or "")[:2000]
    return _parse_verdict(raw), meta
