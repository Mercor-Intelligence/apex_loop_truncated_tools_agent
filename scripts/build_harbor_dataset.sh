#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR=""
OUTPUT_DIR="$ROOT_DIR/.runtime/harbor-dataset"

usage() {
  echo "usage: build_harbor_dataset.sh --source-dir DIR [--output-dir DIR]" >&2
}

while (($#)); do
  case "$1" in
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

[[ -n "$SOURCE_DIR" ]] || { usage; exit 2; }
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
if [[ -d "$OUTPUT_DIR" ]] && find "$OUTPUT_DIR" -mindepth 1 -print -quit | grep -q .; then
  echo "output directory is not empty: $OUTPUT_DIR" >&2
  exit 1
fi

MCP_DIR="${OUTPUT_DIR}.mcp-configs"
uv run apex11-validate "$SOURCE_DIR" \
  --expected-tasks 452 \
  --expected-worlds 31
uv run apex11-build-mcp-configs \
  --dataset "$SOURCE_DIR" \
  --output "$MCP_DIR"
uv run apex11-convert convert \
  --dataset "$SOURCE_DIR" \
  --out "$OUTPUT_DIR" \
  --mcp-config-dir "$MCP_DIR" \
  --version 1.1.0 \
  --harbor-version 0.20.0
uv run apex11-validate-runtime "$OUTPUT_DIR" \
  --expected-tasks 452 \
  --expected-worlds 31
uv run --with harbor==0.20.0 python -m apex11.converter.validate "$OUTPUT_DIR"

echo "Harbor dataset: $OUTPUT_DIR"
