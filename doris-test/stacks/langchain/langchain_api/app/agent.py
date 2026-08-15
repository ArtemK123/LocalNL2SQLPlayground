from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from sqlalchemy.engine import Engine

from app.config import settings
from app.dialect import MYSQL_DIALECT_INSTRUCTIONS
from app.schema_catalog import BirdTablesCatalog, SchemaSelector, SelectionResult, resolve_allowed_schemas
from app.sql_guard import extract_sql, validate_sql


def _arctic_dialect() -> str:
    d = (settings.arctic_sql_dialect or "mysql").strip().lower()
    if d in {"postgresql", "postgres", "pg"}:
        return "postgresql"
    if d in {"mysql", "doris"}:
        return "mysql"
    return "sqlite"


def _arctic_engine_label() -> str:
    d = _arctic_dialect()
    if d == "postgresql":
        return "PostgreSQL"
    if d == "mysql":
        return "Apache Doris (MySQL)"
    return "SQLite"


def _arctic_assistant_prefill() -> str:
    engine = _arctic_engine_label()
    think = f"I will write a concise {engine} query that answers the question."
    if _arctic_dialect() == "mysql":
        think = (
            f"I will write a concise {engine} query using MySQL DATE_FORMAT, CONCAT, and NOW; "
            "not SQLite strftime, ||, or datetime('now')."
        )
    return (
        "Let me solve this step by step.\n"
        "<think>\n"
        f"{think}\n"
        "</think>\n"
        "<answer>\n"
        "```sql\n"
    )


ARCTIC_ASSISTANT_PREFILL = _arctic_assistant_prefill()
ARCTIC_VLLM_STOP = ["```", "</answer>"]

_ARCTIC_OUTPUT_FORMAT = """
Please provide a detailed chain-of-thought reasoning process and include your thought process within `<think>` tags. Your final answer should be enclosed within `<answer>` tags.

Keep the reasoning concise so the final SQL appears quickly (prefer under ~400 tokens of thinking). As soon as you know the query, close `</think>` and emit the ```sql block.

Ensure that your SQL query follows the correct syntax and is formatted as follows:

```sql
-- Your SQL query here
```

Example format:
<think>
Step-by-step reasoning, including self-reflection and corrections if necessary.
</think>
<answer>
```sql
Correct SQL query here
```
</answer>
""".strip()


def _build_chat_llm(model: str) -> BaseChatModel:
    """Ollama or vLLM (OpenAI-compatible) chat client."""
    backend = (settings.llm_backend or "ollama").strip().lower()
    if backend == "vllm":
        from langchain_openai import ChatOpenAI

        base = (settings.vllm_base_url or settings.ollama_host or "").rstrip("/")
        if not base:
            raise ValueError("VLLM_BASE_URL or OLLAMA_HOST required when LLM_BACKEND=vllm")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return ChatOpenAI(
            model=model,
            base_url=base,
            api_key=settings.vllm_api_key or "EMPTY",
            temperature=0.0,
            max_tokens=settings.ollama_num_predict,
            timeout=float(settings.llm_http_timeout_sec),
            max_retries=0,
        )
    return ChatOllama(
        model=model,
        base_url=settings.ollama_host,
        temperature=0.0,
        num_ctx=settings.ollama_num_ctx,
        num_predict=settings.ollama_num_predict,
        reasoning=False,
    )


log = logging.getLogger(__name__)


SQL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are an Apache Doris NL2SQL assistant (MySQL protocol) for the BIRD benchmark.\n"
                "Data is materialized in Doris after PostgreSQL CDC; use schema.table view names from the catalog.\n"
                "Generate exactly one read-only SELECT query.\n"
                "Rules:\n"
                f"{MYSQL_DIALECT_INSTRUCTIONS}\n"
                "- Use only these schemas: {allowed_schemas}\n"
                "- Qualify tables as schema.table when multiple schemas are allowed.\n"
                "- Use only tables and columns listed in the schema reference below.\n"
                "- Never use DDL or DML.\n"
                "- No semicolons.\n"
                "- Use SQL-native literals: numbers and booleans without quotes; quote only text/date literals.\n"
                "- Output format: a single ```sql fenced block containing only the query.\n"
                "- Do not output plans, XML tags, bullet lists, or natural-language explanations."
            ),
        ),
        (
            "human",
            (
                "Schema reference:\n{schema_reference}\n\n"
                "{evidence_block}"
                "Question:\n{question}"
            ),
        ),
    ]
)


def _arctic_sql_prompt() -> ChatPromptTemplate:
    engine = _arctic_engine_label()
    dialect = _arctic_dialect()
    if dialect == "postgresql":
        dialect_hint = (
            "- Use PostgreSQL syntax (double-quote identifiers only when needed; no SQLite backticks).\n"
        )
    elif dialect == "mysql":
        dialect_hint = MYSQL_DIALECT_INSTRUCTIONS + "\n"
    else:
        dialect_hint = ""
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are a data science expert. Below, you are provided with a database schema and a "
                    "natural language question. Your task is to understand the schema and generate a valid "
                    "SQL query to answer the question."
                ),
            ),
            (
                "human",
                (
                    "Database Engine:\n"
                    f"{engine}\n\n"
                    "Database Schema:\n"
                    "{schema_reference}\n"
                    "This schema describes the database's structure, including tables, columns, primary keys, "
                    "foreign keys, and any relevant relationships or constraints.\n\n"
                    "Question:\n"
                    "{question_with_evidence}\n\n"
                    "Instructions:\n"
                    "- Make sure you only output the information that is asked in the question. If the question "
                    "asks for a specific column, make sure to only include that column in the SELECT clause, "
                    "nothing more.\n"
                    "- The generated query should return all of the information asked in the question without "
                    "any missing or extra information.\n"
                    "- Before generating the final SQL query, please think through the steps of how to write "
                    "the query.\n"
                    f"{dialect_hint}\n"
                    "Output Format:\n"
                    f"{_ARCTIC_OUTPUT_FORMAT}\n\n"
                    "Start your reply with: Let me solve this step by step."
                ),
            ),
        ]
    )


ARCTIC_SQL_PROMPT = _arctic_sql_prompt()


def _arctic_repair_prompt() -> ChatPromptTemplate:
    extra = ""
    if _arctic_dialect() == "mysql":
        extra = MYSQL_DIALECT_INSTRUCTIONS + "\n"
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                ("You are a data science expert fixing a SELECT for execution correctness."),
            ),
            (
                "human",
                (
                    "Database Engine:\n"
                    "{engine}\n\n"
                    "Database Schema:\n"
                    "{schema_reference}\n\n"
                    "Question:\n"
                    "{question}\n\n"
                    "Failed SQL:\n"
                    "{sql}\n\n"
                    "Execution error:\n"
                    "{error_message}\n\n"
                    "Allowed schemas: {allowed_schemas}\n\n"
                    "Think briefly, then output one corrected read-only SELECT in a ```sql fence.\n"
                    + extra
                    + "Start your reply with: Let me solve this step by step."
                ),
            ),
        ]
    )


ARCTIC_REPAIR_PROMPT = _arctic_repair_prompt()

ANSWER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You summarize SQL query results for business users in 2-4 sentences.",
        ),
        (
            "human",
            "Question: {question}\nSQL: {sql}\nColumns: {columns}\nRows (JSON): {rows}",
        ),
    ]
)

REASONING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You explain NL2SQL decisions to end users.\n"
                "Return 3-5 concise bullet points.\n"
                "Use only explicit evidence from the question and SQL.\n"
                "Do not reveal hidden chain-of-thought, tokens, or internal reasoning."
            ),
        ),
        (
            "human",
            "Question: {question}\nSQL: {sql}\nColumns: {columns}",
        ),
    ]
)

REPAIR_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are fixing a Doris/MySQL SELECT query for execution correctness.\n"
                "Return exactly one corrected SQL query in a fenced sql block.\n"
                "Rules:\n"
                f"{MYSQL_DIALECT_INSTRUCTIONS}\n"
                "- Use only these schemas: {allowed_schemas}\n"
                "- Keep it read-only SELECT.\n"
                "- No semicolons.\n"
                "- Fix only what is needed to address execution errors.\n"
                "- Never invent tables or columns outside the schema reference."
            ),
        ),
        (
            "human",
            (
                "Question:\n{question}\n\n"
                "Schema reference:\n{schema_reference}\n\n"
                "Failed SQL:\n{sql}\n\n"
                "Execution error:\n{error_message}"
            ),
        ),
    ]
)


def _is_arctic_model(model: str) -> bool:
    lowered = model.lower()
    return "arctic" in lowered and "text2sql" in lowered


def _use_arctic_sql_fence_prefill() -> bool:
    backend = (settings.llm_backend or "ollama").strip().lower()
    return (
        backend == "vllm"
        and bool(settings.arctic_sql_fence_prefill)
        and _is_arctic_model(settings.ollama_primary_model)
    )


class SqlAgent:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.allowed_schemas = resolve_allowed_schemas(engine, settings.allowed_schemas)
        self.use_arctic_prompt = _is_arctic_model(settings.ollama_primary_model)
        self.use_sql_fence_prefill = _use_arctic_sql_fence_prefill()
        self.sql_dialect = _arctic_dialect()
        self.primary = _build_chat_llm(settings.ollama_primary_model)
        self.fallback = _build_chat_llm(settings.ollama_fallback_model)
        if self.use_sql_fence_prefill:
            log.info(
                "Arctic vLLM SQL-fence prefill enabled (stop=%s, max_tokens=%s, dialect=%s)",
                ARCTIC_VLLM_STOP,
                settings.ollama_num_predict,
                self.sql_dialect,
            )
        mode = settings.schema_selector_mode.lower().strip()
        llm_selector = self._select_tables_with_llm if mode in {"llm", "hybrid"} else None
        bird_tables = None
        schema_source = (settings.schema_source or "catalog").strip().lower()
        if schema_source == "bird_tables":
            bird_tables = BirdTablesCatalog(settings.bird_tables_json)
        self.schema_selector = SchemaSelector(
            engine=engine,
            allowed_schemas=self.allowed_schemas,
            enabled=settings.schema_selection_enabled,
            shortlist_top_m=settings.schema_shortlist_top_m,
            final_top_k=settings.schema_final_top_k,
            mode=settings.schema_selector_mode,
            refresh_seconds=settings.schema_refresh_seconds,
            schema_source=schema_source,
            bird_tables=bird_tables,
            include_fk_neighbors=settings.schema_bm25_include_fk,
            llm_selector=llm_selector,
        )

    def _bind_arctic_sql_llm(self, llm: BaseChatModel) -> BaseChatModel:
        if not self.use_sql_fence_prefill:
            return llm
        extra_body = {
            "continue_final_message": True,
            "add_generation_prompt": False,
            "chat_template_kwargs": {
                "continue_final_message": True,
                "add_generation_prompt": False,
            },
        }
        return llm.bind(stop=list(ARCTIC_VLLM_STOP), extra_body=extra_body)

    def _select_tables_with_llm(self, question: str, compact_table_lines: list[str]) -> list[str]:
        if not compact_table_lines:
            return []
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        "Select the most relevant tables for a Doris/MySQL NL2SQL task.\n"
                        "Return ONLY JSON array of schema.table strings.\n"
                        "Keep the list short and include only tables clearly needed."
                    ),
                ),
                (
                    "human",
                    (
                        "Question:\n{question}\n\nCandidate tables (one per line):\n{candidates}\n\n"
                        "Output: JSON array like [\"schema.table\", ...]"
                    ),
                ),
            ]
        ).format_prompt(question=question, candidates="\n".join(compact_table_lines))
        raw = self.primary.invoke(prompt.to_messages()).content
        if isinstance(raw, list):
            raw = "".join(str(part) for part in raw)
        txt = str(raw).strip()
        try:
            parsed = json.loads(txt)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if isinstance(v, str)]
        except json.JSONDecodeError:
            pass
        return []

    @staticmethod
    def _question_with_evidence(question: str, evidence: str | None) -> str:
        q = (question or "").strip()
        ev = (evidence or "").strip()
        if ev:
            return f"{ev}\n{q}"
        return q

    def _format_sql_messages(
        self, question: str, selection: SelectionResult, evidence: str | None = None
    ) -> list[BaseMessage]:
        if self.use_arctic_prompt:
            messages = ARCTIC_SQL_PROMPT.format_prompt(
                schema_reference=selection.schema_reference,
                question_with_evidence=self._question_with_evidence(question, evidence),
            ).to_messages()
            if self.use_sql_fence_prefill:
                messages.append(AIMessage(content=_arctic_assistant_prefill()))
            return messages
        evidence_block = ""
        if evidence and evidence.strip():
            evidence_block = f"Evidence (domain hints):\n{evidence.strip()}\n\n"
        allowed = ", ".join(self.allowed_schemas)
        return SQL_PROMPT.format_prompt(
            allowed_schemas=allowed,
            schema_reference=selection.schema_reference,
            evidence_block=evidence_block,
            question=question,
        ).to_messages()

    def _generate_sql_with(
        self,
        llm: BaseChatModel,
        question: str,
        selection: SelectionResult,
        evidence: str | None = None,
    ) -> str:
        messages = self._format_sql_messages(question, selection, evidence=evidence)
        raw = self._bind_arctic_sql_llm(llm).invoke(messages).content
        if isinstance(raw, list):
            raw = "".join(str(part) for part in raw)
        raw_text = str(raw)
        allowed_schemas, allowed_tables = self._validation_scope(selection)
        try:
            return validate_sql(
                extract_sql(raw_text),
                allowed_tables=allowed_tables,
                allowed_schemas=allowed_schemas,
                dialect=self.sql_dialect,
            )
        except ValueError:
            preview = re.sub(r"\s+", " ", raw_text).strip()[:500]
            log.warning("SQL extract/validate failed; raw preview=%r", preview)
            raise

    def _validation_scope(
        self, selection: SelectionResult
    ) -> tuple[list[str], tuple[str, ...] | None]:
        """Scope guard to the request db_id catalog, not every BIRD schema on the cluster."""
        if selection.db_id and settings.db_id_as_schema:
            schemas = [selection.db_id]
            if selection.allowed_table_fq:
                schemas = sorted({fq.split(".", 1)[0] for fq in selection.allowed_table_fq})
            return schemas, selection.allowed_table_fq or None
        if selection.used_fallback_full_schema:
            return list(self.allowed_schemas), None
        return list(self.allowed_schemas), selection.selected_table_fq

    def generate_sql(
        self,
        question: str,
        *,
        db_id: str | None = None,
        evidence: str | None = None,
    ) -> tuple[str, str, SelectionResult]:
        selection = self.schema_selector.reference_for(
            question, db_id=db_id, evidence=evidence
        )
        return (
            self._generate_sql_with(self.primary, question, selection, evidence=evidence),
            settings.ollama_primary_model,
            selection,
        )

    def repair_sql(
        self,
        *,
        question: str,
        failed_sql: str,
        error_message: str,
        selection: SelectionResult,
        model_used: str,
    ) -> tuple[str, str]:
        llm = self.primary if model_used == settings.ollama_primary_model else self.fallback
        scoped_schemas, _tables = self._validation_scope(selection)
        allowed = ", ".join(scoped_schemas)
        if self.use_arctic_prompt:
            messages = ARCTIC_REPAIR_PROMPT.format_prompt(
                engine=_arctic_engine_label(),
                allowed_schemas=allowed,
                question=question,
                schema_reference=selection.schema_reference,
                sql=failed_sql,
                error_message=error_message[:1500],
            ).to_messages()
            if self.use_sql_fence_prefill:
                messages.append(AIMessage(content=_arctic_assistant_prefill()))
        else:
            messages = REPAIR_PROMPT.format_prompt(
                allowed_schemas=allowed,
                question=question,
                schema_reference=selection.schema_reference,
                sql=failed_sql,
                error_message=error_message[:1500],
            ).to_messages()
        raw = self._bind_arctic_sql_llm(llm).invoke(messages).content
        if isinstance(raw, list):
            raw = "".join(str(part) for part in raw)
        allowed_schemas, allowed_tables = self._validation_scope(selection)
        repaired = validate_sql(
            extract_sql(str(raw)),
            allowed_tables=allowed_tables,
            allowed_schemas=allowed_schemas,
            dialect=self.sql_dialect,
        )
        return repaired, model_used

    def summarize(self, question: str, sql: str, columns: list[str], rows: list[dict[str, Any]]) -> str:
        serialized_rows = json.dumps(rows[:20], default=str)
        prompt = ANSWER_PROMPT.format_prompt(
            question=question,
            sql=sql,
            columns=", ".join(columns),
            rows=serialized_rows,
        )
        out = self.primary.invoke(prompt.to_messages()).content
        if isinstance(out, list):
            return "".join(str(part) for part in out)
        return str(out)

    def explain_sql(self, question: str, sql: str, columns: list[str]) -> str:
        prompt = REASONING_PROMPT.format_prompt(
            question=question,
            sql=sql,
            columns=", ".join(columns),
        )
        out = self.primary.invoke(prompt.to_messages()).content
        if isinstance(out, list):
            return "".join(str(part) for part in out)
        return str(out)
