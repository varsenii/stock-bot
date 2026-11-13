#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

docker run --rm -it \
  --gpus all \
  --network host \
  -v "$PROJECT_ROOT:/app" \
  -v stock-bot-ollama:/root/.ollama \
  stock-bot
