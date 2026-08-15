#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$ROOT_DIR/.runtime"
DATASET_DIR=""
REPO_ID="mercor/apex-agents-v1.1"
SOURCE_EXPLICIT=0
ARCHIPELAGO_DIR="$ROOT_DIR/archipelago"
TASK_ARGS=()

usage() {
  cat >&2 <<'EOF'
usage: prepare_from_hf.sh [--repo-id OWNER/REPO | --dataset-dir DIR] [options]

Options:
  --work-dir DIR       ignored output root (default: ./.runtime)
  --task-id ID         convert one task; repeat for a smoke subset
EOF
}

while (($#)); do
  case "$1" in
    --repo-id) REPO_ID="$2"; SOURCE_EXPLICIT=$((SOURCE_EXPLICIT + 1)); shift 2 ;;
    --dataset-dir) DATASET_DIR="$2"; SOURCE_EXPLICIT=$((SOURCE_EXPLICIT + 1)); shift 2 ;;
    --work-dir) WORK_DIR="$2"; shift 2 ;;
    --task-id) TASK_ARGS+=(--task-id "$2"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

if ((SOURCE_EXPLICIT > 1)); then
  usage
  exit 2
fi
if [[ ! -f "$ARCHIPELAGO_DIR/environment/Dockerfile" ]]; then
  git -C "$ROOT_DIR" submodule update --init --recursive archipelago
fi
test -f "$ARCHIPELAGO_DIR/environment/Dockerfile" || {
  echo "missing Archipelago submodule: $ARCHIPELAGO_DIR" >&2
  exit 1
}
test -f "$ROOT_DIR/runtime/build_images.sh" || { echo "missing runtime bridge" >&2; exit 1; }

mkdir -p "$WORK_DIR"
if [[ -z "$DATASET_DIR" ]]; then
  DATASET_DIR="$WORK_DIR/hf-dataset"
  uv run apex11-download-hf --repo-id "$REPO_ID" --output "$DATASET_DIR"
else
  DATASET_DIR="$(cd "$DATASET_DIR" && pwd)"
fi

uv run apex11-validate "$DATASET_DIR" \
  --expected-tasks 452 \
  --expected-worlds 31 \
  --report "$WORK_DIR/hf_validation.json"

uv run apex11-build-mcp-configs \
  --dataset "$DATASET_DIR" \
  --output "$WORK_DIR/mcp-configs" \
  --report "$WORK_DIR/mcp_config_report.json"

RUNNER_DIR="$WORK_DIR/tasks"
uv run apex11-convert convert \
  --dataset "$DATASET_DIR" \
  --out "$RUNNER_DIR" \
  --mcp-config-dir "$WORK_DIR/mcp-configs" \
  --version 1.1.0 \
  --harbor-version 0.20.0 \
  "${TASK_ARGS[@]}"

uv run apex11-validate-runtime "$RUNNER_DIR" \
  --report "$WORK_DIR/runtime_validation.json"

uv run --with harbor==0.20.0 python -m apex11.converter.validate "$RUNNER_DIR"

echo "Local runnable task repository (gitignored): $RUNNER_DIR"
echo "Next: cd '$RUNNER_DIR' && bash prepare_images.sh && bash run_task.sh <task>"
