#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$ROOT_DIR/.runtime"
REPO_ID="mercor/apex-agents-v1.1"
ARCHIPELAGO_DIR="$ROOT_DIR/archipelago"

usage() {
  cat >&2 <<'EOF'
usage: prepare_from_hf.sh [--repo-id OWNER/REPO] [--work-dir DIR]
EOF
}

while (($#)); do
  case "$1" in
    --repo-id) REPO_ID="$2"; shift 2 ;;
    --work-dir) WORK_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

if [[ ! -f "$ARCHIPELAGO_DIR/environment/Dockerfile" ]]; then
  git -C "$ROOT_DIR" submodule update --init --recursive archipelago
fi
test -f "$ARCHIPELAGO_DIR/environment/Dockerfile" || {
  echo "missing Archipelago submodule: $ARCHIPELAGO_DIR" >&2
  exit 1
}
test -f "$ROOT_DIR/runtime/build_images.sh" || {
  echo "missing runtime bridge" >&2
  exit 1
}

mkdir -p "$WORK_DIR"
RUNNER_DIR="$WORK_DIR/tasks"
if [[ -d "$RUNNER_DIR" ]] && find "$RUNNER_DIR" -mindepth 1 -print -quit | grep -q .; then
  echo "output directory is not empty: $RUNNER_DIR" >&2
  exit 1
fi

uv run hf download "$REPO_ID" \
  --repo-type dataset \
  --local-dir "$RUNNER_DIR"

uv run apex11-validate-runtime "$RUNNER_DIR" \
  --expected-tasks 452 \
  --expected-worlds 31 \
  --report "$WORK_DIR/runtime_validation.json"
uv run --with harbor==0.20.0 python -m apex11.converter.validate "$RUNNER_DIR"

echo "Local runnable task repository (gitignored): $RUNNER_DIR"
echo "Next: cd '$RUNNER_DIR' && bash prepare_images.sh && bash run_task.sh <task>"
