#!/usr/bin/env bash
set -euo pipefail

# ── Load Ollama API key ──────────────────────────────────────────────────
if [[ -f /app/.ollama_api_key ]]; then
  OLLAMA_API_KEY="$(tr -d '[:space:]' < /app/.ollama_api_key)"
  export OLLAMA_API_KEY
fi

# ── Read model name from analysis config ─────────────────────────────────
OLLAMA_MODEL="$(python3 -c "
import yaml, pathlib
try:
    cfg = yaml.safe_load(pathlib.Path('/app/analysis_config.yaml').read_text()) or {}
    print(cfg.get('llm', {}).get('model', 'qwen3:8b'))
except Exception:
    print('qwen3:8b')
")"

# ── Start Ollama server in background ────────────────────────────────────
ollama serve &>/dev/null &

echo "Waiting for Ollama server…"
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
  sleep 1
done
echo "Ollama server ready."

# ── Pull model if not already present ────────────────────────────────────
if ! ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL%%:*}"; then
  echo "Pulling ${OLLAMA_MODEL} (first run only)…"
  ollama pull "$OLLAMA_MODEL"
fi

echo "Model ${OLLAMA_MODEL} ready.  Run:  python3 __main__.py analyze --max-records 1"

exec bash "$@"
