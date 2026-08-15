"""Emit a Harbor dataset from an archipelago-shaped export."""

import json
import re
from pathlib import Path
from typing import Any

from . import worlds as worlds_mod
from .grading import DEFAULT_JUDGE_MODEL, build_grading_config, golden_reference, needs_snapshot
from .profile import DatasetProfile

WORLD_GATEWAY_URL = "http://world:8000/mcp"
DEFAULT_IMAGE_TAG = "v1"
DEFAULT_IMAGE_PREFIX = "archipelago-harbor"
AGENT_TIMEOUT_SEC = 3600
VERIFIER_TIMEOUT_SEC = 3600
COLLECT_TIMEOUT_SEC = 660

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Environment orientation, prepended to every prompt. The original harness gave
# the agent its app tools as a described toolbelt; a stock Harbor agent starts
# with a bare prompt, so without this we would be measuring whether a model
# guesses that an MCP workspace exists rather than the task itself. Harbor's own
# MCP examples orient the agent in instruction.md the same way.
ENVIRONMENT_PREAMBLE = """\
## Your working environment

You are working inside a simulated workplace that is exposed to you over MCP by the
`world` server. The container you run in is intentionally empty — every document,
spreadsheet, email, message and calendar entry for this task lives behind the `world`
MCP tools, and any file you are asked to produce must be created through them.

Applications available in this workspace: {apps}.

If the `world` tools are not in your tool list yet, wait for the MCP server to finish
connecting and retry. An empty local filesystem is expected and never means the task
data is missing.

---

"""


def render_instruction(task: dict[str, Any], profile: DatasetProfile, world: dict[str, Any]) -> str:
    apps = [a.get("service_name", "") for a in world.get(profile.apps_field, [])]
    preamble = ENVIRONMENT_PREAMBLE.format(apps=", ".join(a for a in apps if a))
    return preamble + (task.get(profile.prompt_field) or "").strip() + "\n"


def slugify(name: str, task_id: str) -> str:
    """Stable, unique task identity. Stability matters: a churned name churns
    every digest downstream of it. The task-id suffix guarantees uniqueness."""
    base = _SLUG_STRIP.sub("-", (name or "task").lower()).strip("-") or "task"
    return f"{base[:60].strip('-')}-{task_id.split('_', 1)[-1][:8]}"


def _healthcheck_probe() -> str:
    """Ready only once the world is seeded AND the MCP gateway answers."""
    return (
        "import json,os,sys,urllib.request\n"
        "sys.exit(1) if not os.path.exists('/logs/world/.initial_snapshot_done') else None\n"
        "b=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':"
        "{'protocolVersion':'2024-11-05','capabilities':{},"
        "'clientInfo':{'name':'healthcheck','version':'0'}}}).encode()\n"
        "r=urllib.request.Request('http://localhost:8000/mcp',data=b,"
        "headers={'Content-Type':'application/json',"
        "'Accept':'application/json, text/event-stream'},method='POST')\n"
        "urllib.request.urlopen(r,timeout=10).read(1)\n"
    )


def render_task_toml(
    task: dict[str, Any],
    profile: DatasetProfile,
    slug: str,
    snapshot: bool,
    agent_image: str,
    judge_model: str,
) -> str:
    task_id = task[profile.task_id_field]
    domain = task.get(profile.domain_field) or ""

    if snapshot:
        artifacts = (
            'artifacts = ["/logs/agent/trajectory.json", '
            '{ source = "/logs/world/final_snapshot.tar.gz", service = "world" }, '
            '{ source = "/logs/world/initial_snapshot.tar.gz", service = "world" }]'
        )
        collect = (
            "\n[[verifier.collect]]\n"
            'service = "world"\n'
            f"timeout_sec = {COLLECT_TIMEOUT_SEC}\n"
            'command = "python /app/tools/collect_world_snapshot.py"\n'
        )
    else:
        artifacts = 'artifacts = ["/logs/agent/trajectory.json"]'
        collect = ""

    description = (task.get(profile.prompt_field) or "").strip().split("\n", 1)[0][:180]
    keywords = sorted(
        {"agents", "mcp", profile.name, _SLUG_STRIP.sub("-", domain.lower()).strip("-")}
        - {""}
    )

    return f"""\
schema_version = "1.3"
{artifacts}

[task]
name = "{profile.org}/{slug}"
description = {json.dumps(description)}
keywords = {json.dumps(keywords)}

[metadata]
task_id = "{task_id}"
world_id = "{task[profile.world_id_field]}"
domain = {json.dumps(domain)}
expected_output = {json.dumps(task.get(profile.expected_output_field) or "")}

[agent]
timeout_sec = {AGENT_TIMEOUT_SEC}

[verifier]
environment_mode = "separate"
timeout_sec = {VERIFIER_TIMEOUT_SEC}

[verifier.environment]
cpus = 2
memory_mb = 8192
storage_mb = 20480
network_mode = "public"

[verifier.environment.env]
GRADING_MODEL = "${{GRADING_MODEL:-{judge_model}}}"
LITELLM_PROXY_API_BASE = "${{LITELLM_PROXY_API_BASE:-}}"
LITELLM_PROXY_API_KEY = "${{LITELLM_PROXY_API_KEY:-}}"
OPENAI_API_KEY = "${{OPENAI_API_KEY:-}}"
ANTHROPIC_API_KEY = "${{ANTHROPIC_API_KEY:-}}"
GOOGLE_API_KEY = "${{GOOGLE_API_KEY:-}}"
{collect}
[environment]
docker_image = "{agent_image}"
cpus = 2
memory_mb = 8192
storage_mb = 20480
network_mode = "public"

[[environment.mcp_servers]]
name = "world"
transport = "streamable-http"
url = "{WORLD_GATEWAY_URL}"

[environment.env]
WORLD_TASK_ID = "{task_id}"
"""


def render_compose(
    world_id: str, snapshot: bool, has_overlay: bool, world_image: str
) -> str:
    overlay = '      - "./task_files:/task_files:ro"\n' if has_overlay else ""
    capture = '      WORLD_CAPTURE_INITIAL_SNAPSHOT: "1"\n' if snapshot else ""
    # Seeding a world (and snapshotting it) dominates start-up on big worlds.
    start_period, retries = ("600s", 300) if snapshot else ("300s", 120)
    probe = json.dumps(_healthcheck_probe())

    return f"""\
# Merged on top of harbor's own compose layers. The world boots from a shared
# image and is seeded per trial from a read-only mount, so no trial can alter
# what the next one reads.
services:
  world:
    image: "{world_image}"
    expose:
      - "8000"
    volumes:
      - "../../../worlds/{world_id}:/world:ro"
{overlay}      - "world_logs:/logs/world"
    environment:
      PORT: "8000"
{capture}      FMP_API_KEY: "${{FMP_API_KEY:-}}"
      EDGAR_USER_AGENT: "${{EDGAR_USER_AGENT:-archipelago harbor@example.com}}"
    healthcheck:
      test: ["CMD", "python3", "-c", {probe}]
      interval: 10s
      timeout: 15s
      retries: {retries}
      start_period: {start_period}
  main:
    depends_on:
      world:
        condition: service_healthy
    volumes:
      - "world_logs:/logs/world:ro"
    environment:
      ANTHROPIC_API_KEY: "${{ANTHROPIC_API_KEY:-}}"
      ANTHROPIC_BASE_URL: "${{ANTHROPIC_BASE_URL:-}}"
      GEMINI_API_KEY: "${{GEMINI_API_KEY:-}}"
      GOOGLE_API_KEY: "${{GOOGLE_API_KEY:-}}"
      LITELLM_PROXY_API_BASE: "${{LITELLM_PROXY_API_BASE:-}}"
      LITELLM_PROXY_API_KEY: "${{LITELLM_PROXY_API_KEY:-}}"
      OPENAI_API_KEY: "${{OPENAI_API_KEY:-}}"
volumes:
  world_logs:
"""


def convert_task(
    task: dict[str, Any],
    world: dict[str, Any],
    dataset_root: Path,
    tasks_dir: Path,
    gold_root: Path,
    profile: DatasetProfile,
    judge_model: str,
    world_image: str,
    agent_image: str,
    verifier_image: str,
) -> dict[str, Any]:
    task_id = task[profile.task_id_field]
    slug = slugify(task.get(profile.task_name_field, ""), task_id)
    task_dir = tasks_dir / f"{profile.task_dir_prefix}{slug}"
    env_dir = task_dir / "environment"
    tests_dir = task_dir / "tests"
    for directory in (env_dir, tests_dir):
        directory.mkdir(parents=True, exist_ok=True)

    (task_dir / "instruction.md").write_text(render_instruction(task, profile, world))

    snapshot = needs_snapshot(task, profile)
    overlay_files = worlds_mod.copy_task_overlay(
        task_id, dataset_root, env_dir / "task_files", profile
    )

    (task_dir / "task.toml").write_text(
        render_task_toml(task, profile, slug, snapshot, agent_image, judge_model)
    )
    (env_dir / "docker-compose.yaml").write_text(
        render_compose(
            task[profile.world_id_field], snapshot, bool(overlay_files), world_image
        )
    )

    # Separate verifier mode: harbor never uploads tests/, so the image owns it.
    (tests_dir / "Dockerfile").write_text(
        f"FROM {verifier_image}\nCOPY . /tests/\n"
    )
    (tests_dir / "grading_config.json").write_text(
        json.dumps(build_grading_config(task, profile, judge_model), indent=2) + "\n"
    )
    if snapshot:
        # Marker: a missing snapshot is a grading error, not an empty diff.
        (tests_dir / "needs_snapshot").write_text("")
    elif (tests_dir / "needs_snapshot").exists():
        (tests_dir / "needs_snapshot").unlink()

    # Gold outputs follow the delivery layout customers already read: the record
    # and reference text sit in tests/, the files stay outside the task dir under
    # the dataset's own gold_files/<task_id>/. They are reference data, not a
    # grading input — APEX grades from the prompt, agent output and artifact diff.
    gold_files = worlds_mod.copy_goldens(
        task_id, dataset_root, gold_root / task_id, profile
    )
    reference = golden_reference(task, profile)
    gold_response = task.get(profile.gold_response_field) or ""
    if reference or gold_files:
        (tests_dir / "golden_responses.json").write_text(
            json.dumps(
                [
                    {
                        "golden_text_response": reference or "",
                        "golden_file_responses": None if reference else gold_response,
                        "golden_files_path": f"gold_files/{task_id}" if gold_files else None,
                    }
                ],
                indent=2,
            )
            + "\n"
        )
    if reference:
        (tests_dir / "golden_reference.txt").write_text(reference + "\n")

    return {
        "slug": slug,
        "dir": task_dir.name,
        "task_id": task_id,
        "world_id": task[profile.world_id_field],
        "domain": task.get(profile.domain_field),
        "needs_snapshot": snapshot,
        "overlay_files": overlay_files,
        "gold_files": gold_files,
        "criteria": len(task.get(profile.rubric_field) or []),
    }


def write_registry(
    out_dir: Path, profile: DatasetProfile, records: list[dict[str, Any]], version: str
) -> None:
    """Path-A discovery index. Task entries omit git_url/git_commit_id so they
    default to the containing repo at whatever ref was resolved."""
    registry = [
        {
            "name": profile.name,
            "version": version,
            "description": profile.description,
            "tasks": [
                {"name": f"{profile.org}/{r['slug']}", "path": f"tasks/{r['dir']}"}
                for r in sorted(records, key=lambda r: r["slug"])
            ],
        }
    ]
    (out_dir / "registry.json").write_text(json.dumps(registry, indent=2) + "\n")
