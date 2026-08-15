"""Build Harbor MCP configs while excluding known non-MCP agent services."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .runtime_utils import atomic_json


# Cursor is an alternative agent runtime in Studio, not a world tool. Harbor
# supplies its own agent, so exposing Cursor as an MCP server would be incorrect.
NON_MCP_SERVICES = {
    "svc_31dfee5c48984772a6161c3c5e847e1c": "Cursor",
}


def load_builder(archipelago: Path) -> ModuleType:
    path = archipelago / "harbor" / "tools" / "build_mcp_config.py"
    if not path.is_file():
        raise ValueError(f"missing Archipelago MCP builder: {path}")
    spec = importlib.util.spec_from_file_location("apex11_mcp_builder", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load Archipelago MCP builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config_for_world(
    world: dict[str, Any], builder: ModuleType
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    resolved: list[tuple[str, dict[str, Any]]] = []
    ignored: list[dict[str, str]] = []
    for app in world.get("apps") or []:
        service_id = str(app.get("service_id") or "")
        if service_id in NON_MCP_SERVICES:
            ignored.append(
                {
                    "service_id": service_id,
                    "service_name": str(app.get("service_name") or ""),
                    "reason": "agent runtime, not a world MCP service",
                }
            )
            continue
        try:
            resolved.append(builder.resolve(app))
        except KeyError as exc:
            raise ValueError(
                f"world {world.get('world_id')} has unsupported app {app!r}"
            ) from exc
    config = {"mcpServers": dict(resolved)}
    if not config["mcpServers"]:
        raise ValueError(f"world {world.get('world_id')} resolved to no MCP servers")
    return config, ignored


def build_all(
    dataset: Path,
    archipelago: Path,
    output: Path,
) -> dict[str, Any]:
    worlds_path = dataset / "world_descriptions.json"
    if not worlds_path.is_file():
        raise ValueError(f"missing world index: {worlds_path}")
    worlds = json.loads(worlds_path.read_text())
    if not isinstance(worlds, list):
        raise ValueError("world_descriptions.json must contain a list")
    builder = load_builder(archipelago)
    output.mkdir(parents=True, exist_ok=True)
    ignored_services: list[dict[str, str]] = []
    network_worlds: list[str] = []
    for world in worlds:
        world_id = str(world.get("world_id") or "")
        if not world_id:
            raise ValueError("world index contains a record without world_id")
        config, ignored = config_for_world(world, builder)
        atomic_json(output / f"{world_id}.json", config)
        ignored_services.extend({"world_id": world_id, **item} for item in ignored)
        if builder.requires_network(config):
            network_worlds.append(world_id)
    return {
        "worlds": len(worlds),
        "configs": len(list(output.glob("world_*.json"))),
        "network_worlds": sorted(network_worlds),
        "ignored_non_mcp_services": ignored_services,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--archipelago", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        report = build_all(
            args.dataset.resolve(),
            args.archipelago.resolve(),
            args.output.resolve(),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.exit(str(exc))
    if args.report:
        atomic_json(args.report.resolve(), report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
