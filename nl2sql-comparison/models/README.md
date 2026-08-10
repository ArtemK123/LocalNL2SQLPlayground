# Dual-model GPU catalog notes (AWS)
#
# SQL stacks (langchain, premsql, vanna, wrenai): OLLAMA_SQL_MODEL
#   Tag: arctic-text2sql-r1-7b:q4_k_m
#   Source: mradermacher/Arctic-Text2SQL-R1-7B-GGUF → Arctic-Text2SQL-R1-7B.Q4_K_M.gguf
#   Created on GPU via stack/ollama/ensure-arctic-q4.sh (not an official Ollama Hub pull).
#   Official Hub a-kore/Arctic-Text2SQL-R1-7B is Q8_0 (~8.1GB); Q4_K_M is ~4.8GB for L4 latency.
#
# Chat2DB / dbgpt: OLLAMA_GENERAL_MODEL = qwen2.5-coder:14b-instruct-q8_0
#
# Switch: scripts/aws/set-gpu-model.ps1 -ModelProfile sql|general
