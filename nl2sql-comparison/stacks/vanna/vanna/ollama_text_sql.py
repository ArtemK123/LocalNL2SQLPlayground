"""Ollama LLM without native tool calling + synthetic run_sql from model text.

Many text-to-SQL models (e.g. OmniSQL-7B Q4, Arctic-Text2SQL) return 400 from Ollama when `tools` are sent.
This wrapper strips `tools` from the API payload and, if the stream ends with no tool
calls, parses a SELECT from markdown fences or plain text and emits a run_sql ToolCall.
"""

from __future__ import annotations

import re
from typing import Any, AsyncGenerator, Dict, List, Optional

from vanna.core.llm import LlmRequest, LlmStreamChunk
from vanna.core.tool import ToolCall
from vanna.integrations.ollama.llm import OllamaLlmService


def extract_select_sql(text: str) -> Optional[str]:
    if not text or not text.strip():
        return None
    t = text
    m = re.search(r"```sql\s*([\s\S]*?)```", t, re.IGNORECASE)
    if m:
        s = m.group(1).strip().rstrip(";").strip()
        if s.upper().startswith("SELECT"):
            return s
    m = re.search(r"```\s*(SELECT[\s\S]*?)```", t, re.IGNORECASE)
    if m:
        s = m.group(1).strip().rstrip(";").strip()
        if s.upper().startswith("SELECT"):
            return s
    idx = t.upper().rfind("SELECT")
    if idx < 0:
        return None
    tail = t[idx:].strip()
    part = tail.split(";")[0].strip()
    if part.upper().startswith("SELECT"):
        return part
    return None


class OllamaLlmServiceTextSql(OllamaLlmService):
    """Same as OllamaLlmService but compatible with Ollama models that reject `tools`."""

    def _build_payload(self, request: LlmRequest) -> Dict[str, Any]:
        payload = super()._build_payload(request)
        payload.pop("tools", None)
        return payload

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        payload = self._build_payload(request)

        try:
            stream = self._client.chat(**payload, stream=True)
        except Exception as e:
            raise RuntimeError(f"Ollama streaming request failed: {str(e)}") from e

        accumulated_tool_calls: List[ToolCall] = []
        last_finish: Optional[str] = None
        accumulated_content = ""

        for chunk in stream:
            message = chunk.get("message", {})
            content = message.get("content")
            if content:
                accumulated_content += content
                yield LlmStreamChunk(content=content)

            tool_calls = self._extract_tool_calls_from_message(message)
            if tool_calls:
                accumulated_tool_calls.extend(tool_calls)

            if chunk.get("done"):
                last_finish = chunk.get("done_reason", "stop")

        if accumulated_tool_calls:
            yield LlmStreamChunk(
                tool_calls=accumulated_tool_calls, finish_reason=last_finish or "stop"
            )
            return

        sql = extract_select_sql(accumulated_content)
        if sql:
            yield LlmStreamChunk(
                tool_calls=[
                    ToolCall(
                        id="text_sql_0",
                        name="run_sql",
                        arguments={"sql": sql},
                    )
                ],
                finish_reason=last_finish or "stop",
            )
        else:
            yield LlmStreamChunk(finish_reason=last_finish or "stop")
