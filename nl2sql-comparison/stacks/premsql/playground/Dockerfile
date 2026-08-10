FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY start_playground_api.py run_playground_ui.py register_agent_session.py patch_playground_chat.py ./

CMD ["python", "start_playground_api.py"]
