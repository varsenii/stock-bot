#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

docker build -t stock-bot -f "$PROJECT_ROOT/docker/Dockerfile" "$PROJECT_ROOT"
