"""Vanna Agents + Ollama + PostgreSQL (OLAP) for postgre_etl NL2SQL."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from vanna import Agent, AgentConfig
from vanna.core.registry import ToolRegistry
from vanna.core.system_prompt import DefaultSystemPromptBuilder
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.integrations.local import LocalFileSystem
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.integrations.postgres import PostgresRunner

from ollama_text_sql import OllamaLlmServiceTextSql
from vanna.servers.fastapi import VannaFastAPIServer
from vanna.tools import RunSqlTool
from vanna.core.user.models import User


class AnonymousUserResolver(UserResolver):
    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id="local",
            username="local",
            email="local@postgre_etl.demo",
        )


def _load_schema_bundle() -> str:
    root = Path(os.environ.get("VANNA_SCHEMA_DIR", "/app/schema"))
    if not root.is_dir():
        return "-- (no schema files mounted)"
    chunks: list[str] = []
    for path in sorted(root.glob("*.sql")):
        chunks.append(f"-- === {path.name} ===\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks) if chunks else "-- (empty schema dir)"


def _build_system_prompt() -> str:
    schema = _load_schema_bundle()
    today = date.today().isoformat()
    db = os.environ.get("PG_DATABASE", "olap")
    return f"""You are a local OLAP assistant (PostgreSQL). Today's date is {today}.

You query PostgreSQL. Database: {db}. Use the actual relations from the provided schema bundle.

Rules:
- Prefer SELECT. Do not run DDL or destructive SQL unless the user explicitly requests it.
- Do not invent schema names (for example mart, analytics, staging) unless they are present in the schema bundle below.
- Put the final query in a single markdown fenced block: ```sql\\nSELECT ...\\n``` (this stack executes that SQL).

=== SCHEMA (DDL + views) ===
{schema}
"""


def create_agent() -> Agent:
    ollama_host = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
    model = os.environ.get("OLLAMA_MODEL", "hf.co/mradermacher/OmniSQL-7B-GGUF:Q4_K_M")
    num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))

    llm = OllamaLlmServiceTextSql(model=model, host=ollama_host, temperature=0.2, num_ctx=num_ctx)

    sql_runner = PostgresRunner(
        host=os.environ.get("PG_HOST", "postgres"),
        port=int(os.environ.get("PG_PORT", "5432")),
        database=os.environ.get("PG_DATABASE", "olap"),
        user=os.environ.get("PG_USER", "olap"),
        password=os.environ.get("PG_PASSWORD", ""),
    )

    fs = LocalFileSystem(working_directory="/tmp/vanna_fs")
    tools = ToolRegistry()
    tools.register_local_tool(RunSqlTool(sql_runner=sql_runner, file_system=fs), [])

    return Agent(
        llm_service=llm,
        tool_registry=tools,
        user_resolver=AnonymousUserResolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(stream_responses=True, max_tool_iterations=5),
        system_prompt_builder=DefaultSystemPromptBuilder(base_prompt=_build_system_prompt()),
    )


_agent = create_agent()
_server = VannaFastAPIServer(_agent)
app = _server.create_app()
