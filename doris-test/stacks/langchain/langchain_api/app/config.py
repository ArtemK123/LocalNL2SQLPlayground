from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8011, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    db_uri: str = Field(alias="DB_URI")
    # mysql|doris = Doris FE MySQL protocol; postgresql = BIRD PG (backend flip).
    db_dialect: str = Field(default="mysql", alias="DB_DIALECT")
    db_allowed_schemas: str = Field(
        default="",
        alias="DB_ALLOWED_SCHEMAS",
    )
    query_timeout_ms: int = Field(default=5000, alias="QUERY_TIMEOUT_MS")
    max_result_rows: int = Field(default=200, alias="MAX_RESULT_ROWS")

    ollama_host: str = Field(default="http://ollama:11434", alias="OLLAMA_HOST")
    ollama_primary_model: str = Field(default="qwen2.5:7b-instruct", alias="OLLAMA_PRIMARY_MODEL")
    ollama_fallback_model: str = Field(default="sqlcoder:7b", alias="OLLAMA_FALLBACK_MODEL")
    ollama_num_ctx: int = Field(default=4096, alias="OLLAMA_NUM_CTX")
    ollama_num_predict: int = Field(default=512, alias="OLLAMA_NUM_PREDICT")
    # ollama = ChatOllama; vllm = OpenAI-compatible (ChatOpenAI) at VLLM_BASE_URL/v1
    llm_backend: str = Field(default="ollama", alias="LLM_BACKEND")
    vllm_base_url: str = Field(default="", alias="VLLM_BASE_URL")
    vllm_api_key: str = Field(default="EMPTY", alias="VLLM_API_KEY")
    llm_http_timeout_sec: float = Field(default=20.0, alias="LLM_HTTP_TIMEOUT_SEC")
    arctic_sql_fence_prefill: bool = Field(default=True, alias="ARCTIC_SQL_FENCE_PREFILL")
    # Prompt "Database Engine:" line: mysql|doris|postgresql|sqlite
    arctic_sql_dialect: str = Field(default="mysql", alias="ARCTIC_SQL_DIALECT")
    schema_selection_enabled: bool = Field(default=True, alias="SCHEMA_SELECTION_ENABLED")
    schema_shortlist_top_m: int = Field(default=25, alias="SCHEMA_SHORTLIST_TOP_M")
    schema_final_top_k: int = Field(default=8, alias="SCHEMA_FINAL_TOP_K")
    # catalog = live information_schema; bird_tables = Study OmniSQL CREATE TABLE from tables.json
    schema_source: str = Field(default="bird_tables", alias="SCHEMA_SOURCE")
    bird_tables_json: str = Field(
        default="/app/data/dev_tables.json",
        alias="BIRD_TABLES_JSON",
    )
    schema_bm25_include_fk: bool = Field(default=True, alias="SCHEMA_BM25_INCLUDE_FK")
    # heuristic = BM25 + token overlap (no extra LLM); bm25 = Study pure BM25; hybrid/llm add LLM
    schema_selector_mode: str = Field(default="bm25", alias="SCHEMA_SELECTOR_MODE")
    schema_refresh_seconds: int = Field(default=3600, alias="SCHEMA_REFRESH_SECONDS")
    schema_selection_debug: bool = Field(default=False, alias="SCHEMA_SELECTION_DEBUG")
    # When true (Doris multi-schema / CDC), filter live catalog to schema_name == db_id.
    # Set false for single-schema Postgres (all minidev tables in public).
    db_id_as_schema: bool = Field(default=True, alias="DB_ID_AS_SCHEMA")
    sql_repair_max_retries: int = Field(default=0, alias="SQL_REPAIR_MAX_RETRIES")
    # execute = run against DB_URI; skip = return SQL without server-side exec (harness scores).
    sql_exec_mode: str = Field(default="skip", alias="SQL_EXEC_MODE")
    # Skip summarize + explain LLM calls after SQL execution (single generation pass).
    nl2sql_fast_mode: bool = Field(default=True, alias="NL2SQL_FAST_MODE")

    @property
    def allowed_schemas(self) -> list[str]:
        return [v.strip() for v in self.db_allowed_schemas.split(",") if v.strip()]

    @property
    def is_mysql(self) -> bool:
        if self.db_dialect.lower() in ("mysql", "doris"):
            return True
        return self.db_uri.startswith("mysql")


settings = Settings()
