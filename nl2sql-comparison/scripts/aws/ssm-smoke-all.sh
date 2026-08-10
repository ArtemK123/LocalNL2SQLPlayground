#!/bin/bash
# Backward-compatible alias for ssm-smoke-stack.sh (one stack per SSM invocation).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/ssm-smoke-stack.sh"
