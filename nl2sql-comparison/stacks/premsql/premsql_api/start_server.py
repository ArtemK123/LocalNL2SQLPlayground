from __future__ import annotations

import os
from typing import Optional

from premsql.agents import BaseLineAgent
from premsql.agents.tools import SimpleMatplotlibTool
from premsql.executors import ExecutorUsingLangChain
from premsql.generators.base import Text2SQLGeneratorBase
from premsql.playground import AgentServer
import requests


class HttpOllamaGenerator(Text2SQLGeneratorBase):
    def __init__(
        self,
        model_name: str,
        experiment_name: str,
        type: str,
        ollama_host: str = "http://ollama:11434",
        experiment_folder: Optional[str] = None,
    ):
        self.model_name = model_name
        self._ollama_host = ollama_host
        super().__init__(
            experiment_name=experiment_name,
            experiment_folder=experiment_folder,
            type=type,
        )

    @property
    def load_client(self):
        return requests.Session()

    @property
    def load_tokenizer(self):
        return None

    @property
    def model_name_or_path(self):
        return self.model_name

    def generate(
        self,
        data_blob: dict,
        temperature: float = 0.0,
        max_new_tokens: int = 256,
        postprocess: bool = True,
        **kwargs,
    ) -> str:
        prompt = data_blob["prompt"]
        response = self.client.post(
            f"{self._ollama_host}/api/chat",
            json={
                "model": self.model_name_or_path,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_new_tokens},
            },
            timeout=300,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        return self.postprocess(content) if postprocess else content


def build_agent() -> BaseLineAgent:
    ollama_host = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
    text2sql_model_name = os.environ.get(
        "PREMSQL_TEXT2SQL_MODEL", "anindya/prem1b-sql-ollama-fp116"
    )
    analysis_model_name = os.environ.get("PREMSQL_ANALYSIS_MODEL", "llama3.2:1b")
    db_uri = os.environ["PREMSQL_DB_URI"]
    session_name = os.environ.get("PREMSQL_SESSION_NAME", "local_olap")
    auto_filter_tables = (
        os.environ.get("PREMSQL_AUTO_FILTER_TABLES", "false").strip().lower() == "true"
    )

    text2sql_model = HttpOllamaGenerator(
        model_name=text2sql_model_name,
        experiment_name="premsql-local-text2sql",
        type="test",
        ollama_host=ollama_host,
    )
    analyser_model = HttpOllamaGenerator(
        model_name=analysis_model_name,
        experiment_name="premsql-local-analysis",
        type="test",
        ollama_host=ollama_host,
    )

    return BaseLineAgent(
        session_name=session_name,
        db_connection_uri=db_uri,
        specialized_model1=text2sql_model,
        specialized_model2=analyser_model,
        executor=ExecutorUsingLangChain(),
        auto_filter_tables=auto_filter_tables,
        plot_tool=SimpleMatplotlibTool(),
    )


if __name__ == "__main__":
    bind_host = os.environ.get("API_HOST", "0.0.0.0")
    # Hostname other containers use (Playground stores this from /session_info).
    advertise_host = os.environ.get("PREMSQL_AGENT_ADVERTISE_HOST", "premsql-api")
    app_port = int(os.environ.get("API_PORT", "8010"))
    agent = build_agent()
    server = AgentServer(agent=agent, url=advertise_host, port=app_port)
    import uvicorn

    uvicorn.run(server.app, host=bind_host, port=app_port)
