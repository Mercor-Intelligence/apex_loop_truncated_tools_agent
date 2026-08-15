"""Validate staged Harbor task files and world archives."""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path
from typing import Any


def validate(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    tasks_root = root / "tasks"
    worlds_root = root / "worlds"
    tasks = (
        sorted(path for path in tasks_root.iterdir() if path.is_dir())
        if tasks_root.is_dir()
        else []
    )
    worlds = (
        sorted(path for path in worlds_root.iterdir() if path.is_dir())
        if worlds_root.is_dir()
        else []
    )

    partials = sorted(root.rglob("*.part")) + sorted(root.rglob("*.tmp"))
    if partials:
        errors.append(f"found {len(partials)} incomplete temporary file(s)")

    archive_files = 0
    archive_members = 0
    for world in worlds:
        for name in ("filesystem.tar.gz", "apps_data.tar.gz"):
            archive = world / name
            if not archive.is_file() or archive.stat().st_size == 0:
                errors.append(f"missing or empty archive: {archive.relative_to(root)}")
                continue
            try:
                with tarfile.open(archive, "r:gz") as handle:
                    members = [member for member in handle.getmembers() if member.isfile()]
            except (OSError, tarfile.TarError) as exc:
                errors.append(f"invalid archive {archive.relative_to(root)}: {exc}")
                continue
            if not members:
                errors.append(f"archive has no files: {archive.relative_to(root)}")
                continue
            archive_files += 1
            archive_members += len(members)

        config_path = world / "mcp_config.json"
        try:
            config = json.loads(config_path.read_text())
            if not config.get("mcpServers"):
                errors.append(f"empty MCP config: {config_path.relative_to(root)}")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid MCP config {config_path.relative_to(root)}: {exc}")

    required_task_files = (
        "instruction.md",
        "task.toml",
        "environment/docker-compose.yaml",
        "tests/Dockerfile",
        "tests/grading_config.json",
    )
    for task in tasks:
        for name in required_task_files:
            path = task / name
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"missing or empty task file: {path.relative_to(root)}")

    return {
        "valid": not errors,
        "counts": {
            "tasks": len(tasks),
            "worlds": len(worlds),
            "archives": archive_files,
            "archive_members": archive_members,
        },
        "errors": errors,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--expected-tasks", type=int)
    parser.add_argument("--expected-worlds", type=int)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = validate(args.root.resolve())
    counts = report["counts"]
    if args.expected_tasks is not None and counts["tasks"] != args.expected_tasks:
        report["errors"].append(
            f"expected {args.expected_tasks} tasks, found {counts['tasks']}"
        )
    if args.expected_worlds is not None and counts["worlds"] != args.expected_worlds:
        report["errors"].append(
            f"expected {args.expected_worlds} worlds, found {counts['worlds']}"
        )
    report["valid"] = not report["errors"]
    rendered = json.dumps(report, indent=2) + "\n"
    print(rendered, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered)
    if not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
