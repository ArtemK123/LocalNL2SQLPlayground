#!/bin/sh
OLLAMA_BASE="${OLLAMA_HOST:-http://ollama:11434}"
OLLAMA_BASE="${OLLAMA_BASE%/}"
LLM_MODEL="${OLLAMA_PRIMARY_MODEL:-qwen2.5:7b-instruct}"
EMBED_MODEL="${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"
COL_BATCH="${WREN_COLUMN_INDEXING_BATCH_SIZE:-10}"
TABLE_RETRIEVAL="${WREN_TABLE_RETRIEVAL_SIZE:-75}"
TABLE_COL_RETRIEVAL="${WREN_TABLE_COLUMN_RETRIEVAL_SIZE:-100}"

sed \
  -e "s|http://ollama:11434/v1|${OLLAMA_BASE}/v1|g" \
  -e "s|http://ollama:11434|${OLLAMA_BASE}|g" \
  -e "s|ollama_chat/a-kore/Arctic-Text2SQL-R1-7B|ollama_chat/${LLM_MODEL}|g" \
  -e "s|openai/nomic-embed-text|openai/${EMBED_MODEL}|g" \
  -e "s/column_indexing_batch_size: [0-9][0-9]*/column_indexing_batch_size: ${COL_BATCH}/" \
  -e "s/table_retrieval_size: [0-9][0-9]*/table_retrieval_size: ${TABLE_RETRIEVAL}/" \
  -e "s/table_column_retrieval_size: [0-9][0-9]*/table_column_retrieval_size: ${TABLE_COL_RETRIEVAL}/" \
  /templates/config.yaml >/out/config.yaml

echo "Rendered Wren config: ollama=${OLLAMA_BASE} llm=ollama_chat/${LLM_MODEL} embed=${EMBED_MODEL} col_batch=${COL_BATCH} table_retrieval=${TABLE_RETRIEVAL}"
