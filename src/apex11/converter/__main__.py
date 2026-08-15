"""CLI for converting an archipelago-shaped dataset into a Harbor dataset."""

import argparse
import json
import sys
from pathlib import Path

from .convert import (
    DEFAULT_IMAGE_PREFIX,
    DEFAULT_IMAGE_TAG,
    convert_task,
    write_registry,
)
from .grading import DEFAULT_JUDGE_MODEL
from .profile import get_profile
from .scaffold import write_scaffold
from .worlds import convert_world
from apex11 import mcp_config


def _load(path: Path):
    if not path.exists():
        sys.exit(f"missing index file: {path}")
    return json.loads(path.read_text())


def cmd_convert(args: argparse.Namespace) -> None:
    profile = get_profile(args.profile)
    dataset_root = Path(args.dataset).resolve()
    out_dir = Path(args.out).resolve()
    tasks = _load(dataset_root / profile.tasks_index)
    worlds = {w[profile.world_id_field]: w for w in _load(dataset_root / profile.worlds_index)}

    if args.task_id:
        tasks = [t for t in tasks if t[profile.task_id_field] in set(args.task_id)]
    elif args.world_id:
        tasks = [t for t in tasks if t[profile.world_id_field] in set(args.world_id)]
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        sys.exit("no tasks selected")

    images = {
        "world_image": f"{args.image_prefix}-world:{args.image_tag}",
        "agent_image": f"{args.image_prefix}-agent:{args.image_tag}",
        "verifier_image": f"{args.image_prefix}-verifier:{args.image_tag}",
    }

    needed_worlds = sorted({t[profile.world_id_field] for t in tasks})
    print(f"converting {len(tasks)} task(s) across {len(needed_worlds)} world(s) -> {out_dir}")
    if args.dry_run:
        for task in tasks:
            print(f"  would emit {task[profile.task_id_field]} ({task.get(profile.task_name_field)})")
        return

    (out_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (out_dir / "worlds").mkdir(parents=True, exist_ok=True)

    world_reports = []
    for index, world_id in enumerate(needed_worlds, 1):
        if world_id not in worlds:
            sys.exit(f"world {world_id} referenced by a task but absent from the world index")
        print(f"[world {index}/{len(needed_worlds)}] {world_id}")
        report = convert_world(
            worlds[world_id],
            dataset_root,
            out_dir / "worlds",
            profile,
            mcp_config,
            force=args.force_worlds,
            mcp_config_dir=Path(args.mcp_config_dir) if args.mcp_config_dir else None,
        )
        world_reports.append(report)
        print(f"    {report}")

    records = []
    for index, task in enumerate(tasks, 1):
        record = convert_task(
            task,
            worlds[task[profile.world_id_field]],
            dataset_root,
            out_dir / "tasks",
            out_dir / "gold_files",
            profile,
            args.judge_model,
            **images,
        )
        records.append(record)
        print(f"[task {index}/{len(tasks)}] {record['slug']}"
              f" (snapshot={record['needs_snapshot']}, criteria={record['criteria']})")

    write_registry(out_dir, profile, records, args.version)

    summary = {
        "tasks": len(records),
        "worlds": len(world_reports),
        "snapshot_tasks": sum(1 for r in records if r["needs_snapshot"]),
        "tasks_with_inputs": sum(1 for r in records if r["overlay_files"]),
        "tasks_with_gold_files": sum(1 for r in records if r["gold_files"]),
        "network_worlds": [r["world_id"] for r in world_reports if r.get("requires_network")],
        "images": images,
    }
    (out_dir / "conversion_report.json").write_text(json.dumps(summary, indent=2) + "\n")

    write_scaffold(
        out_dir,
        profile,
        summary,
        image_prefix=args.image_prefix,
        image_tag=args.image_tag,
        harbor_version=args.harbor_version,
        judge_model=args.judge_model,
        agent=args.agent,
        agent_model=args.agent_model,
    )
    print("\n" + json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="apex11-convert", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    convert = sub.add_parser("convert", help="emit a Harbor dataset")
    convert.add_argument("--dataset", required=True, help="archipelago-shaped dataset root")
    convert.add_argument("--out", required=True, help="output Harbor dataset dir")
    convert.add_argument("--profile", default="apex-agents")
    convert.add_argument("--version", default="1.0")
    convert.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    convert.add_argument("--image-prefix", default=DEFAULT_IMAGE_PREFIX)
    convert.add_argument("--image-tag", default=DEFAULT_IMAGE_TAG)
    convert.add_argument("--task-id", action="append", help="convert only these task ids")
    convert.add_argument("--world-id", action="append", help="convert only these worlds")
    convert.add_argument("--limit", type=int)
    convert.add_argument(
        "--force-worlds", action="store_true", help="repack world archives even if present"
    )
    convert.add_argument("--dry-run", action="store_true")
    convert.add_argument("--harbor-version", default="0.14.0")
    convert.add_argument("--agent", default="claude-code")
    convert.add_argument("--agent-model", default="anthropic/claude-opus-4-5")
    convert.add_argument(
        "--mcp-config-dir",
        help="dir of pre-generated <world_id>.json /apps payloads (e.g. ArCo-derived "
        "from the source pipeline); falls back to the static server mapping",
    )
    convert.set_defaults(func=cmd_convert)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
