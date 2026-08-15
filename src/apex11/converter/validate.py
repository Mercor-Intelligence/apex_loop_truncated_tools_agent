"""Lint a converted dataset against Harbor's own task contract.

Runs under the harbor tool's interpreter so the checks come from Harbor's real
models, not a reimplementation of them. A task that fails `is_valid_dir` is
*silently skipped* by directory scans, so catching it here is the difference
between a 480-task dataset and a quietly 300-task one.

    uv run --with harbor==0.20.0 python -m apex11.converter.validate <dataset-dir>
"""

import json
import sys
import tomllib
from pathlib import Path

try:
    from harbor.models.task.task import Task
    from harbor.models.task.config import TaskConfig
except ImportError:  # pragma: no cover - guidance beats a traceback
    sys.exit(
        "harbor is not importable. Run this with the harbor tool interpreter:\n"
        "  uv run --with harbor==0.20.0 python -m apex11.converter.validate <dataset-dir>"
    )


def check_task(task_dir: Path) -> list[str]:
    errors: list[str] = []

    if not Task.is_valid_dir(task_dir):
        errors.append("harbor would skip this dir (Task.is_valid_dir is False)")

    config_path = task_dir / "task.toml"
    if not config_path.exists():
        return errors + ["missing task.toml"]

    try:
        config = TaskConfig.model_validate(tomllib.loads(config_path.read_text()))
    except Exception as exc:  # noqa: BLE001
        return errors + [f"task.toml does not validate: {exc}"]

    if config.task is None or not config.task.name:
        errors.append("[task].name is required to publish or index the task")
    if not (task_dir / "instruction.md").exists():
        errors.append("missing instruction.md")
    if not (task_dir / "environment").is_dir():
        errors.append("missing environment/ directory")

    separate = config.verifier.environment_mode == "separate"
    if not separate and not (task_dir / "tests/test.sh").exists():
        errors.append("shared verifier mode needs tests/test.sh")
    if separate and not (task_dir / "tests/Dockerfile").exists():
        errors.append("separate verifier mode needs tests/Dockerfile to own /tests")

    grading = task_dir / "tests/grading_config.json"
    if not grading.exists():
        errors.append("missing tests/grading_config.json")
    else:
        try:
            parsed = json.loads(grading.read_text())
        except json.JSONDecodeError as exc:
            errors.append(f"grading_config.json is not valid JSON: {exc}")
        else:
            if not parsed.get("verifiers"):
                errors.append("grading_config.json has no verifiers")
            if not parsed.get("eval_configs"):
                errors.append("grading_config.json has no eval_configs")
            ids = {e["eval_config_id"] for e in parsed.get("eval_configs", [])}
            unknown = {
                v["eval_config_id"]
                for v in parsed.get("verifiers", [])
                if v.get("eval_config_id") not in ids
            }
            if unknown:
                errors.append(f"verifiers reference unknown eval configs: {sorted(unknown)}")

    # A snapshot-graded task must actually collect the snapshots it grades on.
    needs_snapshot = (task_dir / "tests/needs_snapshot").exists()
    collects_world = any(c.service == "world" for c in config.verifier.collect)
    if needs_snapshot and not collects_world:
        errors.append("needs_snapshot is set but no [[verifier.collect]] for the world")
    if needs_snapshot:
        sources = {
            a.source if hasattr(a, "source") else a for a in config.artifacts
        }
        for required in (
            "/logs/world/initial_snapshot.tar.gz",
            "/logs/world/final_snapshot.tar.gz",
        ):
            if required not in sources:
                errors.append(f"needs_snapshot but {required} is not in artifacts")

    compose = task_dir / "environment/docker-compose.yaml"
    if not compose.exists():
        errors.append("missing environment/docker-compose.yaml (no world sidecar)")
    else:
        body = compose.read_text()
        if "/world:ro" not in body:
            errors.append("world data mount is not read-only")

    return errors


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1]).resolve()
    task_dirs = sorted(p for p in (root / "tasks").iterdir() if p.is_dir())
    if not task_dirs:
        sys.exit(f"no task dirs under {root / 'tasks'}")

    failures = {}
    for task_dir in task_dirs:
        if errors := check_task(task_dir):
            failures[task_dir.name] = errors

    # Registry entries must resolve, or `-d <name>` silently under-selects.
    registry_path = root / "registry.json"
    if registry_path.exists():
        for dataset in json.loads(registry_path.read_text()):
            for entry in dataset["tasks"]:
                if not (root / entry["path"]).is_dir():
                    failures.setdefault("registry.json", []).append(
                        f"path does not exist: {entry['path']}"
                    )

    print(f"checked {len(task_dirs)} task(s) in {root}")
    for name, errors in failures.items():
        print(f"\n  {name}")
        for error in errors:
            print(f"    - {error}")

    if failures:
        sys.exit(f"\n{len(failures)} item(s) failed validation")
    print("all tasks satisfy the harbor task contract")


if __name__ == "__main__":
    main()
