"""Repack world snapshots into what the Harbor world sidecar seeds from.

Source snapshots are one zip per world containing ``filesystem/`` and either
``.apps_data/`` (legacy exports) or ``apps_data/`` (current Studio exports). The
gateway's ``/data/populate`` takes one tar.gz per subsystem, rooted at that
subsystem — so each zip becomes two archives plus the world's MCP config.
"""

import json
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from apex11 import mcp_config

from .profile import DatasetProfile

SUBSYSTEM_ARCHIVES = {"filesystem": "filesystem.tar.gz", ".apps_data": "apps_data.tar.gz"}
WORLD_SOURCE_ALIASES = {
    "filesystem": ("filesystem",),
    ".apps_data": (".apps_data", "apps_data"),
}


def _tar_subsystem(source: Path, dest: Path) -> int:
    entries = sorted(source.rglob("*"))
    files = sum(1 for p in entries if p.is_file())
    if not files:
        return 0
    partial = dest.with_name(dest.name + ".part")
    partial.unlink(missing_ok=True)
    try:
        with tarfile.open(partial, "w:gz") as tar:
            # Checkouts of HF datasets store files as symlinks into the blob cache.
            tar.dereference = True
            for entry in entries:
                tar.add(entry, arcname=str(entry.relative_to(source)), recursive=False)
        partial.replace(dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return files


def convert_world(
    world: dict[str, Any],
    dataset_root: Path,
    out_dir: Path,
    profile: DatasetProfile,
    mcp_builder,
    force: bool = False,
    mcp_config_dir: Path | None = None,
) -> dict[str, Any]:
    """Emit worlds/<world_id>/ with the two seed archives and the MCP config."""
    world_id = world[profile.world_id_field]
    world_out = out_dir / world_id
    world_out.mkdir(parents=True, exist_ok=True)

    # The dataset stores an /apps payload, not a derivation. Studio builds the
    # same MCPServerConfig shape from ArCo, which needs DB access the OSS side
    # does not have — so a caller that can derive it (the studio pipeline) passes
    # configs in, and everyone else falls back to the static server mapping.
    supplied = (mcp_config_dir / f"{world_id}.json") if mcp_config_dir else None
    if supplied and supplied.exists():
        config = json.loads(supplied.read_text())
        config_source = "supplied"
    else:
        config = mcp_builder.build_mcp_config(world.get(profile.apps_field, []))
        config_source = "derived"
    if not config.get("mcpServers"):
        raise ValueError(f"world {world_id} resolved to an empty MCP config")
    (world_out / "mcp_config.json").write_text(json.dumps(config, indent=2) + "\n")

    archive = dataset_root / profile.world_archive.format(world_id=world_id)
    if not archive.exists():
        raise FileNotFoundError(f"world archive missing: {archive}")

    counts: dict[str, int] = {}
    targets = {s: world_out / name for s, name in SUBSYSTEM_ARCHIVES.items()}
    if not force and all(p.exists() for p in targets.values()):
        return {
            "world_id": world_id,
            "skipped": True,
            "mcp_config": config_source,
            "requires_network": mcp_builder.requires_network(config),
        }

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)
        for subsystem, dest in targets.items():
            sources = [
                Path(tmp) / name
                for name in WORLD_SOURCE_ALIASES[subsystem]
                if (Path(tmp) / name).is_dir()
            ]
            if len(sources) > 1:
                raise ValueError(
                    f"world {world_id} contains multiple roots for {subsystem}: "
                    f"{[source.name for source in sources]}"
                )
            if sources:
                counts[subsystem] = _tar_subsystem(sources[0], dest)
            elif dest.exists():
                dest.unlink()

    if not counts.get("filesystem"):
        raise ValueError(f"world {world_id} produced no filesystem archive")

    return {
        "world_id": world_id,
        "files": counts,
        "mcp_config": config_source,
        "servers": sorted(config["mcpServers"]),
        "requires_network": mcp_builder.requires_network(config),
    }


def copy_task_overlay(
    task_id: str, dataset_root: Path, dest: Path, profile: DatasetProfile
) -> int:
    """Copy per-task input files, preserving the subsystem roots the world seeds from."""
    source = dataset_root / profile.task_files.format(task_id=task_id)
    if not source.is_dir():
        return 0
    copied = 0
    for subsystem in SUBSYSTEM_ARCHIVES:
        sub_source = source / subsystem
        if not sub_source.is_dir():
            continue
        sub_dest = dest / subsystem
        if sub_dest.exists():
            shutil.rmtree(sub_dest)
        shutil.copytree(sub_source, sub_dest, symlinks=False)
        copied += sum(1 for p in sub_dest.rglob("*") if p.is_file())
    return copied


def copy_goldens(
    task_id: str, dataset_root: Path, dest: Path, profile: DatasetProfile
) -> int:
    source = dataset_root / profile.golden_files.format(task_id=task_id)
    if not source.is_dir():
        return 0
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, symlinks=False)
    return sum(1 for p in dest.rglob("*") if p.is_file())
