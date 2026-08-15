#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${1:-$ROOT_DIR/.runtime/harbor-dataset}"
REPO_ID="${2:-mercor/apex-agents-v1.1}"

uv run apex11-validate-runtime "$SOURCE_DIR" \
  --expected-tasks 452 \
  --expected-worlds 31
uv run --with harbor==0.20.0 python -m apex11.converter.validate "$SOURCE_DIR"
uv run hf upload "$REPO_ID" "$SOURCE_DIR" . \
  --repo-type dataset \
  --private \
  --exclude ".cache/**" \
  --exclude ".gitattributes" \
  --exclude ".gitignore" \
  --exclude "conversion_report.json" \
  --delete "export_report.json" \
  --delete "metadata.json" \
  --delete "task_ids.txt" \
  --delete "tasks_and_rubrics.json" \
  --delete "world_descriptions.json" \
  --delete "task_files/**" \
  --delete "world_files_zipped/**"
