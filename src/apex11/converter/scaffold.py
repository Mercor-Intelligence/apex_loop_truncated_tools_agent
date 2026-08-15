"""Dataset-level files: how someone who just cloned the repo actually runs it."""

import json
from pathlib import Path
from typing import Any

from .profile import DatasetProfile


def _prepare_images(tag: str, prefix: str) -> str:
    return f"""\
#!/usr/bin/env bash
#
# Build the three images every task in this dataset shares: the world sidecar,
# the agent container and the verifier. Run once — world data is mounted per
# trial rather than baked, so no image is per-world or per-task.
#
# Takes ~20-40 min on a cold cache; the images total roughly 8 GB.
#
set -euo pipefail

TAG="${{HARBOR_IMAGE_TAG:-{tag}}}"
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
BUNDLE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHECKOUT="$BUNDLE_ROOT/archipelago"
BUILDER="$BUNDLE_ROOT/runtime/build_images.sh"

test -f "$CHECKOUT/environment/Dockerfile" || {{
    echo "missing submodule; run: git submodule update --init --recursive" >&2
    exit 1
}}
test -x "$BUILDER" || {{ echo "missing runtime builder: $BUILDER" >&2; exit 1; }}

ARCHIPELAGO_DIR="$CHECKOUT" HARBOR_IMAGE_PREFIX="{prefix}" bash "$BUILDER" "$TAG"

docker run --rm --entrypoint /app/.venv/bin/python "{prefix}-world:$TAG" -c \
    'from runner.main import app; assert app is not None'
docker run --rm --entrypoint sh "{prefix}-verifier:$TAG" -c \
    'test -x /app/grading/.venv/bin/python && /app/grading/.venv/bin/python --version'

echo
echo "Ready. Run a task with:  bash run_task.sh <task-dir-name>"
"""


def _run_task(prefix: str, tag: str, harbor_version: str) -> str:
    return f"""\
#!/usr/bin/env bash
#
# Run one task from this dataset.
#
#   bash run_task.sh <task-dir-name> [extra harbor args...]
#
# Env: MODEL, AGENT, GRADING_MODEL, OUTPUT_DIR.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
BUNDLE_ROOT="$(cd "$ROOT/../.." && pwd)"
TASK="${{1:-}}"
[ -n "$TASK" ] || {{ echo "usage: run_task.sh <task-dir-name>" >&2; exit 2; }}
shift || true

TASK_DIR="$ROOT/tasks/$TASK"
[ -d "$TASK_DIR" ] || {{ echo "no such task: $TASK_DIR" >&2; exit 2; }}

# Pin the CLI because the task schema and separate-verifier collect hooks are
# version-sensitive. Use an installed binary when it matches; otherwise uvx
# provides the tested version without another setup step.
if [ "$(harbor --version 2>/dev/null || true)" = "{harbor_version}" ]; then
    RUNNER=(harbor)
else
    RUNNER=(uvx --from harbor=={harbor_version} harbor)
fi

TAG="${{HARBOR_IMAGE_TAG:-{tag}}}"
for image in world agent verifier; do
    docker image inspect "{prefix}-$image:$TAG" >/dev/null 2>&1 || {{
        echo "missing image {prefix}-$image:$TAG — run: bash prepare_images.sh" >&2
        exit 1
    }}
done

cfg() {{ python3 -c "import json;print(json.load(open('$ROOT/models.json'))['$1'])"; }}
MODEL="${{MODEL:-$(cfg agent_model)}}"
AGENT="${{AGENT:-$(cfg agent)}}"
export GRADING_MODEL="${{GRADING_MODEL:-$(cfg judge_model)}}"

ENV_ARGS=()
ENV_FILE="${{APEX_ENV_FILE:-$ROOT/.env}}"
if [[ ! -f "$ENV_FILE" && -f "$BUNDLE_ROOT/.env" ]]; then
    ENV_FILE="$BUNDLE_ROOT/.env"
fi
if [[ -f "$ENV_FILE" ]]; then
    ENV_ARGS+=(--env-file "$ENV_FILE")
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${{line#"${{line%%[![:space:]]*}}"}}"
        [[ -z "$line" || "${{line:0:1}}" == "#" ]] && continue
        line="${{line#export }}"
        key="${{line%%=*}}"
        key="${{key%"${{key##*[![:space:]]}}"}}"
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {{
            echo "invalid key in $ENV_FILE: $key" >&2
            exit 2
        }}
        printf -v template '${{%s}}' "$key"
        ENV_ARGS+=(--agent-env "$key=$template" --verifier-env "$key=$template")
    done < "$ENV_FILE"
fi

set -- -a "$AGENT" "$@"

# --no-delete keeps containers and logs after the trial; harbor's delete path
# also runs `compose down --rmi all`, which the -keep image aliases survive.
exec "${{RUNNER[@]}}" run -p "$TASK_DIR" \\
    -m "$MODEL" -e docker -y \\
    -o "${{OUTPUT_DIR:-$ROOT/jobs}}" \\
    "${{ENV_ARGS[@]}}" \\
    --no-delete "$@"
"""


def _readme(
    profile: DatasetProfile,
    summary: dict[str, Any],
    _tag: str,
    _harbor_version: str,
) -> str:
    return f"""\
---
pretty_name: APEX Agents 1.1
license: cc-by-4.0
task_categories:
- other
tags:
- agents
- harbor
- mcp
- benchmark
---

# APEX Agents 1.1

{profile.description}

This dataset contains {summary["tasks"]} ready-to-run Harbor tasks across
{summary["worlds"]} worlds.

## Run

```bash
git clone --recurse-submodules https://github.com/Mercor-Intelligence/apex-agents-1.1.git
cd apex-agents-1.1
uv sync
uv run hf download mercor/apex-agents-v1.1 \\
  --repo-type dataset \\
  --local-dir .runtime/tasks
cp .env.example .env
bash .runtime/tasks/prepare_images.sh
bash .runtime/tasks/run_task.sh mercor-world418-tk-02-2bdbc68c
```

Put provider credentials in `.env`. Any valid `KEY=VALUE` entry is forwarded to
both the agent and verifier. The default models use `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY`.
"""


def write_scaffold(
    out_dir: Path,
    profile: DatasetProfile,
    summary: dict[str, Any],
    *,
    image_prefix: str,
    image_tag: str,
    harbor_version: str,
    judge_model: str,
    agent: str,
    agent_model: str,
) -> None:
    (out_dir / "prepare_images.sh").write_text(_prepare_images(image_tag, image_prefix))
    (out_dir / "run_task.sh").write_text(
        _run_task(image_prefix, image_tag, harbor_version)
    )
    for script in ("prepare_images.sh", "run_task.sh"):
        (out_dir / script).chmod(0o755)

    (out_dir / "models.json").write_text(
        json.dumps(
            {"agent": agent, "agent_model": agent_model, "judge_model": judge_model},
            indent=2,
        )
        + "\n"
    )
    (out_dir / "README.md").write_text(
        _readme(profile, summary, image_tag, harbor_version)
    )
    (out_dir / ".env.example").write_text(
        "# Any valid KEY=VALUE entry is forwarded to the agent and verifier.\n"
        "ANTHROPIC_API_KEY=\n"
        "OPENAI_API_KEY=\n"
    )

    # World archives are large binaries; task dirs stay plain text so harbor can
    # read them without git-lfs materializing anything first.
    (out_dir / ".gitattributes").write_text(
        "worlds/**/*.tar.gz filter=lfs diff=lfs merge=lfs -text\n"
    )
    (out_dir / ".gitignore").write_text(
        ".archipelago/\njobs*/\nautomation/.venv/\n**/__pycache__/\n*.pyc\n"
    )
