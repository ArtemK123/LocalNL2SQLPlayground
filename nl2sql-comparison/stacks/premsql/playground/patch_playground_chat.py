"""Monkey-patch PremSQL Streamlit chat UI for None agent messages (upstream bug)."""
from __future__ import annotations

import streamlit as st

from premsql.agents.models import ExitWorkerOutput
from premsql.agents.utils import convert_exit_output_to_agent_output
from premsql.playground.backend.api.pydantic_models import CompletionCreationRequest
from premsql.playground.frontend.components import chat as chat_mod


def apply_playground_chat_patches() -> None:
    if getattr(chat_mod.ChatComponent, "_nl2sql_patched", False):
        return

    _orig_output = chat_mod.ChatComponent._streamlit_chat_output
    _orig_render = chat_mod.ChatComponent.render_chat_env

    def _streamlit_chat_output_safe(self, message):  # noqa: ANN001
        if message is None:
            st.warning(
                "No assistant payload for this turn (agent memory miss or failed pipeline). "
                "Try asking again or check premsql-api logs."
            )
            return
        return _orig_output(self, message)

    def _render_chat_env_safe(self, session_name: str) -> None:
        session_info = self.backend_client.get_session(session_name=session_name)
        if session_info.status_code == 500:
            st.error(f"Failed to render chat History for session: {session_name}")
            return

        session = session_info.sessions[0]
        session_db_path = session.session_db_path
        base_url = session.base_url

        history = chat_mod.AgentInteractionMemory(
            session_name=session_name, db_path=session_db_path
        )

        messages = history.generate_messages_from_session(
            session_name=session_name, server_mode=True
        )
        if not messages:
            st.warning("No chat history available for this session.")
        else:
            for message in messages:
                with st.chat_message("user"):
                    st.markdown(getattr(message, "question", "") or "(no question text)")
                with st.chat_message("assistant"):
                    _streamlit_chat_output_safe(self, message)

        base_url = f"http://{base_url}" if not str(base_url).startswith("http") else base_url
        is_session_online_status = self.inference_client.is_online(base_url=base_url)
        if is_session_online_status != 200:
            st.divider()
            st.warning(
                f"Session ended. Restart Agent Server to start the session at: {base_url}"
            )
        else:
            if prompt := st.chat_input("What is your question?"):
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        response = self.backend_client.create_completion(
                            CompletionCreationRequest(
                                session_name=session_name, question=prompt
                            )
                        )
                        if response.status_code == 200:
                            msg = history.get_by_message_id(message_id=response.message_id)
                            if msg is None and response.message is not None:
                                msg = response.message
                            if isinstance(msg, ExitWorkerOutput):
                                msg = convert_exit_output_to_agent_output(exit_output=msg)
                            _streamlit_chat_output_safe(self, msg)
                        else:
                            err = getattr(response, "error_message", None) or "Unknown error"
                            st.error(f"Something went wrong: {err}")

    chat_mod.ChatComponent._streamlit_chat_output = _streamlit_chat_output_safe
    chat_mod.ChatComponent.render_chat_env = _render_chat_env_safe
    chat_mod.ChatComponent._nl2sql_patched = True
