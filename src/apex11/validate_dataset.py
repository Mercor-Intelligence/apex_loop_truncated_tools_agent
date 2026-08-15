"""Validate an archipelago-shaped APEX dataset and select smoke tasks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .runtime_utils import atomic_json, valid_world_zip


NETWORK_SERVICES = {"edgar sec", "fmp"}
FINAL_ANSWER_OUTPUT = "message_in_console"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise ValueError(f"missing required file: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def task_dir_name(task: dict[str, Any]) -> str:
    name = str(task.get("task_name") or "task")
    task_id = str(task.get("task_id") or "")
    base = _SLUG_STRIP.sub("-", name.lower()).strip("-") or "task"
    slug = f"{base[:60].strip('-')}-{task_id.split('_', 1)[-1][:8]}"
    return f"mercor-{slug}"


def dir_file_count(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.rglob("*") if child.is_file())


def select_smoke_tasks(
    tasks: list[dict[str, Any]], worlds: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    def is_network(task: dict[str, Any]) -> bool:
        apps = worlds[task["world_id"]].get("apps") or []
        names = {str(app.get("service_name") or "").lower() for app in apps}
        return bool(names & NETWORK_SERVICES)

    def usable(task: dict[str, Any]) -> bool:
        return bool(
            task.get("prompt")
            and task.get("rubric")
            and task.get("gold_response")
            and task.get("expected_output")
            and not is_network(task)
        )

    def score(task: dict[str, Any], prefer_file: bool = False) -> tuple[int, ...]:
        is_file = task.get("expected_output") != FINAL_ANSWER_OUTPUT
        return (
            int(is_file == prefer_file),
            int(bool(task.get("task_input_files"))),
            min(len(task.get("rubric") or []), 10),
            -len(str(task.get("prompt") or "")),
        )

    selected: list[dict[str, Any]] = []
    for domain in sorted({str(task.get("domain") or "") for task in tasks}):
        candidates = [
            task
            for task in tasks
            if task.get("domain") == domain
            and task.get("expected_output") == FINAL_ANSWER_OUTPUT
            and usable(task)
        ]
        if candidates:
            selected.append(max(candidates, key=score))

    file_candidates = [
        task
        for task in tasks
        if task.get("expected_output") != FINAL_ANSWER_OUTPUT and usable(task)
    ]
    if file_candidates:
        file_task = max(file_candidates, key=lambda task: score(task, True))
        if file_task["task_id"] not in {task["task_id"] for task in selected}:
            selected.append(file_task)

    return [
        {
            "task_id": task["task_id"],
            "task_name": task["task_name"],
            "task_directory": task_dir_name(task),
            "world_id": task["world_id"],
            "domain": task["domain"],
            "expected_output": task["expected_output"],
            "has_input_files": bool(task.get("task_input_files")),
            "rubric_count": len(task.get("rubric") or []),
        }
        for task in selected
    ]


def validate(
    root: Path,
    *,
    allow_missing_files: bool,
    expected_tasks: int | None,
    expected_worlds: int | None,
) -> dict[str, Any]:
    tasks = load_json(root / "tasks_and_rubrics.json")
    worlds_list = load_json(root / "world_descriptions.json")
    metadata = load_json(root / "metadata.json")
    if not isinstance(tasks, list) or not isinstance(worlds_list, list):
        raise ValueError("task and world indexes must be JSON lists")

    errors: list[str] = []
    warnings: list[str] = []
    task_ids = [str(task.get("task_id") or "") for task in tasks]
    world_ids = [str(world.get("world_id") or "") for world in worlds_list]
    worlds = {world["world_id"]: world for world in worlds_list if world.get("world_id")}

    if len(task_ids) != len(set(task_ids)):
        errors.append("task IDs are not unique")
    if len(world_ids) != len(set(world_ids)):
        errors.append("world IDs are not unique")
    if expected_tasks is not None and len(tasks) != expected_tasks:
        errors.append(f"task count {len(tasks)} != expected {expected_tasks}")
    if expected_worlds is not None and len(worlds_list) != expected_worlds:
        errors.append(f"world count {len(worlds_list)} != expected {expected_worlds}")

    metadata_counts = (metadata or {}).get("counts") or {}
    if metadata_counts.get("tasks") != len(tasks):
        errors.append("metadata task count does not match tasks_and_rubrics.json")
    if metadata_counts.get("worlds") != len(worlds_list):
        errors.append("metadata world count does not match world_descriptions.json")

    bad_tasks: dict[str, list[str]] = {}
    for task in tasks:
        task_id = str(task.get("task_id") or "<missing-task-id>")
        issues: list[str] = []
        for key in (
            "task_id",
            "task_name",
            "world_id",
            "domain",
            "prompt",
            "rubric",
            "expected_output",
            "gold_response",
            "gold_response_type",
        ):
            if is_missing(task.get(key)):
                issues.append(f"missing {key}")
        if task.get("world_id") not in worlds:
            issues.append(f"references missing world {task.get('world_id')}")
        rubric = task.get("rubric") or []
        if isinstance(rubric, list):
            verifier_ids = [str(item.get("verifier_id") or "") for item in rubric]
            if len(verifier_ids) != len(set(verifier_ids)):
                issues.append("rubric verifier IDs are not unique")
            if any(not item.get("criteria") for item in rubric):
                issues.append("rubric contains empty criteria")
        else:
            issues.append("rubric is not a list")

        input_dir = root / "task_files" / task_id
        if task.get("task_input_files") and not allow_missing_files:
            if dir_file_count(input_dir) == 0:
                issues.append("task_input_files is set but downloaded directory is empty")
        if task.get("gold_response_type") == "file" and not allow_missing_files:
            if dir_file_count(root / "gold_files" / task_id) == 0:
                issues.append("file golden is set but downloaded directory is empty")
        if issues:
            bad_tasks[task_id] = issues

    bad_worlds: dict[str, list[str]] = {}
    for world in worlds_list:
        world_id = str(world.get("world_id") or "<missing-world-id>")
        issues: list[str] = []
        for key in ("world_id", "world_name", "world_description", "domain", "apps"):
            if is_missing(world.get(key)):
                issues.append(f"missing {key}")
        archive_path = root / "world_files_zipped" / f"{world_id}.zip"
        if not allow_missing_files and not valid_world_zip(archive_path):
            issues.append("world archive is missing or invalid")
        if issues:
            bad_worlds[world_id] = issues

    if bad_tasks:
        errors.append(f"{len(bad_tasks)} task record(s) failed validation")
    if bad_worlds:
        errors.append(f"{len(bad_worlds)} world record(s) failed validation")

    junk = [str(path.relative_to(root)) for path in root.rglob(".DS_Store")]
    if junk:
        errors.append(f"found {len(junk)} .DS_Store file(s)")

    unreferenced_worlds = sorted(set(worlds) - {task.get("world_id") for task in tasks})
    if unreferenced_worlds:
        warnings.append(f"{len(unreferenced_worlds)} world(s) have no selected task")

    expected_output_counts = Counter(str(task.get("expected_output")) for task in tasks)
    domain_counts = Counter(str(task.get("domain")) for task in tasks)
    smoke = select_smoke_tasks(tasks, worlds)
    total_bytes = sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file()
        and not any(
            part in {".cache", ".git", ".venv", "__pycache__"}
            for part in path.relative_to(root).parts
        )
    )
    report = {
        "valid": not errors,
        "root": str(root),
        "counts": {
            "tasks": len(tasks),
            "worlds": len(worlds_list),
            "tasks_with_inputs": sum(1 for task in tasks if task.get("task_input_files")),
            "text_goldens": sum(
                1 for task in tasks if task.get("gold_response_type") == "text"
            ),
            "file_goldens": sum(
                1 for task in tasks if task.get("gold_response_type") == "file"
            ),
            "downloaded_task_file_dirs": sum(
                1 for task in tasks if dir_file_count(root / "task_files" / task["task_id"])
            ),
            "downloaded_golden_file_dirs": sum(
                1 for task in tasks if dir_file_count(root / "gold_files" / task["task_id"])
            ),
            "world_archives": sum(
                1
                for world in worlds_list
                if (root / "world_files_zipped" / f"{world['world_id']}.zip").is_file()
            ),
            "total_bytes": total_bytes,
        },
        "domains": dict(sorted(domain_counts.items())),
        "expected_outputs": dict(sorted(expected_output_counts.items())),
        "smoke_tasks": smoke,
        "errors": errors,
        "warnings": warnings,
        "bad_tasks": bad_tasks,
        "bad_worlds": bad_worlds,
        "junk": junk,
    }
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--allow-missing-files", action="store_true")
    parser.add_argument("--expected-tasks", type=int)
    parser.add_argument("--expected-worlds", type=int)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--smoke-manifest", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        report = validate(
            args.root.resolve(),
            allow_missing_files=args.allow_missing_files,
            expected_tasks=args.expected_tasks,
            expected_worlds=args.expected_worlds,
        )
    except ValueError as exc:
        sys.exit(str(exc))
    if args.report:
        atomic_json(args.report.resolve(), report)
    if args.smoke_manifest:
        atomic_json(args.smoke_manifest.resolve(), report["smoke_tasks"])
    print(json.dumps({key: report[key] for key in ("valid", "counts", "domains", "expected_outputs", "smoke_tasks", "errors", "warnings")}, indent=2))
    if not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
