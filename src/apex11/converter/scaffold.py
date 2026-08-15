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
CHECKOUT="$BUNDLE_ROOT/vendor/archipelago"
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

set -- -a "$AGENT" "$@"

# --no-delete keeps containers and logs after the trial; harbor's delete path
# also runs `compose down --rmi all`, which the -keep image aliases survive.
exec "${{RUNNER[@]}}" run -p "$TASK_DIR" \\
    -m "$MODEL" -e docker -y \\
    -o "${{OUTPUT_DIR:-$ROOT/jobs}}" \\
    --no-delete "$@"
"""


def _readme(
    profile: DatasetProfile, summary: dict[str, Any], tag: str, harbor_version: str
) -> str:
    network = summary.get("network_worlds") or []
    network_note = (
        f"\n{len(network)} world(s) reach external APIs and need credentials "
        "(`FMP_API_KEY`, `EDGAR_USER_AGENT`); every other world runs offline.\n"
        if network
        else ""
    )
    return f"""\
---
license: cc-by-4.0
task_categories:
- other
tags:
- agents
- harbor
- mcp
- benchmark
---

# {profile.name} (Harbor format)

{profile.description}

A native [Harbor](https://harborframework.com) rendering of the
[`mercor/{profile.name}`](https://huggingface.co/datasets/mercor/{profile.name})
benchmark: {summary['tasks']} tasks across {summary['worlds']} worlds, runnable with
any Harbor agent. Grading uses the same archipelago rubric evaluator as the
published leaderboard.

## Quick start

```bash
pip install harbor=={harbor_version}          # or: uv tool install harbor=={harbor_version}
git clone <this repo> && cd {profile.name}-harbor
git lfs pull                                  # world seed archives are LFS-backed

bash prepare_images.sh                        # once: builds the three shared images
bash run_task.sh <task-dir-name>              # run a single task
harbor run -p tasks/ -n 4 -a claude-code -m <model>   # run the whole set
```

The repository also carries the local-only build workflow under `automation/`.
After the private HF dataset exists, it can reconstruct and validate a fresh
Harbor tree directly from that download:

```bash
cd automation
export HF_TOKEN="hf_..."
./scripts/prepare_from_hf.sh --repo-id <org/private-dataset>
```

The downloader refuses a public HF repository. Until publication, pass
`--dataset-dir <local-hf-payload>` to exercise the identical conversion path
without creating or changing any remote repository.

Any Harbor agent works — the workspace is reached over MCP, not through the agent's own
filesystem:

```bash
AGENT=opencode     bash run_task.sh <task-dir-name>
AGENT=archipelago  bash run_task.sh <task-dir-name>   # the agent of record
```

## How a task runs

Each task boots three containers:

| Container | Role |
|---|---|
| `world` | the archipelago environment, serving one MCP gateway at `http://world:8000/mcp` |
| `main` | where the agent runs; it reaches the world only over MCP |
| verifier | grades after the agent stops, using the archipelago rubric evaluator |

World seed data is **mounted read-only and seeded on boot**, never baked into an
image, so one set of images serves every world and no trial can alter what
another trial reads.
{network_note}
### Running more than one task

Harbor's teardown runs `compose down --rmi all`. Because one image set serves every
task, the first trial to finish would otherwise delete what the rest need —
`prepare_images.sh` tags a `…-keep` alias per image to prevent that. Keep those
aliases, or each trial re-pulls several GB.

Keep the tree intact when copying it somewhere else: each task mounts its world
with a path relative to its own `environment/` directory, so `worlds/` has to stay
a sibling of `tasks/`.

If a trial produces no reward file, Harbor errors it rather than scoring zero.
That is an infrastructure failure — retry it, don't record it as a result.

Each `instruction.md` opens with a short note telling the agent its workspace is
behind the `world` MCP server. That is load-bearing: Harbor attaches MCP servers
asynchronously, and an agent that starts before they land sees an empty container
and gives up with a confident zero. Don't strip it.

## Layout

```
registry.json          harbor dataset index
prepare_images.sh      builds the world / agent / verifier images
run_task.sh            single-task launcher
models.json            default agent and judge models
worlds/<world_id>/     per-world seed archives + MCP config
gold_files/<task_id>/  expert reference outputs (see below)
tasks/<task>/
  instruction.md       the prompt
  task.toml            harbor task config
  environment/         world sidecar compose (+ per-task input files)
  tests/               grading config, gold reference, verifier Dockerfile
```

## Agents and model routing

Agents talk to their model provider directly, so routing everything through one
OpenAI-compatible proxy (LiteLLM and friends) needs the right base URL per agent.
These are the combinations we have actually run:

| Agent | Base URL | Notes |
|---|---|---|
| `claude-code` | `ANTHROPIC_BASE_URL=<proxy>` (**no** `/v1`) | its CLI appends `/v1/messages` itself |
| `opencode` | `ANTHROPIC_BASE_URL=<proxy>/v1` | its provider appends only `/messages`, so the base must carry `/v1` |
| `archipelago` | none | the runner reads `LITELLM_PROXY_API_BASE` / `_API_KEY` |

Set `ANTHROPIC_API_KEY` to the proxy key in both stock cases.

```bash
export ANTHROPIC_BASE_URL="${{PROXY%/}}"       # claude-code
export ANTHROPIC_BASE_URL="${{PROXY%/}}/v1"    # opencode
export ANTHROPIC_API_KEY="$PROXY_KEY"
```

Two gotchas worth knowing before a large run:

- **opencode wedges on buffered proxies.** Its provider defaults to a 10-second
  response-header timeout; a proxy that only sends headers after the full
  generation times out every real call and retries forever. Disable it:
  ```bash
  harbor run ... --agent-env 'OPENCODE_CONFIG_CONTENT={{"autoupdate":false,"provider":{{"openai":{{"options":{{"headerTimeout":false}}}}}}}}'
  ```
- **claude-code caps output tokens.** Long answers can hit its 32,000-token
  ceiling; raise it with `--agent-env CLAUDE_CODE_MAX_OUTPUT_TOKENS=120000`.

## Grading

Rubric-based: each task carries 1-10 binary criteria, and a judge model grades
each independently from the prompt, the agent's output, and the artifact diff
between the initial and final world snapshots.

Gold outputs ship as reference material (`tests/golden_reference.txt`,
`tests/golden_responses.json`, `gold_files/<task_id>/`). Matching the published
methodology, **they are not shown to the judge**.

Set `GRADING_MODEL` to pick the judge, and `LITELLM_PROXY_API_BASE` /
`LITELLM_PROXY_API_KEY` to route it through a proxy.

## Intended use

Model evaluation only. Training, fine-tuning or parameter fitting on this data is
forbidden, as is crawling or scraping it.
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
    (out_dir / "prepare_images.sh").write_text(
        _prepare_images(image_tag, image_prefix)
    )
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

    # World archives are large binaries; task dirs stay plain text so harbor can
    # read them without git-lfs materializing anything first.
    (out_dir / ".gitattributes").write_text(
        "worlds/**/*.tar.gz filter=lfs diff=lfs merge=lfs -text\n"
    )
    (out_dir / ".gitignore").write_text(
        ".archipelago/\n"
        "jobs*/\n"
        "automation/.venv/\n"
        "**/__pycache__/\n"
        "*.pyc\n"
    )
