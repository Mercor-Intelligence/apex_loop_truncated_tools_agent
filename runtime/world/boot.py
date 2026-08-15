#!/usr/bin/env python3
"""Boot an Archipelago world inside a Harbor compose sidecar.

Seeds the subsystems from the mounted world data, mounts the world's MCP servers
on the gateway, and (when asked) captures the initial snapshot the verifier diffs
against. Every step fails closed: a half-seeded world grades as a false zero, so
the container dies instead and Harbor errors the trial.
"""

import json
import os
import re
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import httpx

PORT = os.environ.get("PORT", "8000")
ENV_URL = f"http://localhost:{PORT}"
WORLD_DATA_DIR = Path(os.environ.get("WORLD_DATA_DIR", "/world"))
TASK_FILES_DIR = Path(os.environ.get("TASK_FILES_DIR", "/task_files"))
LOGS_DIR = Path(os.environ.get("WORLD_LOGS_DIR", "/logs/world"))
CAPTURE_INITIAL = os.environ.get("WORLD_CAPTURE_INITIAL_SNAPSHOT", "") == "1"

READY_MARKER = LOGS_DIR / ".initial_snapshot_done"
INITIAL_SNAPSHOT = LOGS_DIR / "initial_snapshot.tar.gz"
SNAPSHOT_HOOKS = Path("/app/tools/snapshot_hooks.json")

# filesystem/ and .apps_data/ are the two subsystems /data/populate understands;
# both the world zips and the per-task overlays are rooted on them.
SUBSYSTEMS = {"filesystem": "filesystem.tar.gz", ".apps_data": "apps_data.tar.gz"}

HEALTH_TIMEOUT_SEC = int(os.environ.get("WORLD_HEALTH_TIMEOUT_SEC", "300"))
POPULATE_TIMEOUT_SEC = float(os.environ.get("WORLD_POPULATE_TIMEOUT_SEC", "1800"))
APPS_TIMEOUT_SEC = float(os.environ.get("WORLD_APPS_TIMEOUT_SEC", "600"))
SNAPSHOT_TIMEOUT_SEC = float(os.environ.get("WORLD_SNAPSHOT_TIMEOUT_SEC", "900"))


def log(msg: str) -> None:
    print(f"[boot {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def die(msg: str) -> None:
    log(f"ERROR: {msg}")
    sys.exit(1)


def wait_for_health() -> None:
    deadline = time.time() + HEALTH_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            if httpx.get(f"{ENV_URL}/health", timeout=5).status_code == 200:
                log("gateway healthy")
                return
        except httpx.RequestError:
            pass
        time.sleep(1)
    die(f"gateway did not become healthy within {HEALTH_TIMEOUT_SEC}s")


def populate_archive(archive: Path, subsystem: str) -> None:
    """Stream a tar.gz straight from the read-only mount into a subsystem."""
    log(f"populating {subsystem} from {archive.name} ({archive.stat().st_size / 1e6:.1f} MB)")
    with archive.open("rb") as fh:
        resp = httpx.post(
            f"{ENV_URL}/data/populate",
            files={"archive": (archive.name, fh, "application/gzip")},
            params={"subsystem": subsystem},
            timeout=POPULATE_TIMEOUT_SEC,
        )
    if resp.status_code != 200:
        die(f"populate {subsystem} failed: {resp.status_code} {resp.text[:500]}")
    log(f"  {subsystem}: {resp.json()}")


def populate_dir(source: Path, subsystem: str) -> None:
    """Tar a plain directory in-container, then populate. Task overlays ship as
    real files so they stay readable (and LFS-free) in the dataset repo."""
    entries = [p for p in source.rglob("*")]
    if not any(p.is_file() for p in entries):
        return
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / f"{subsystem.strip('.')}_overlay.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            # HF checkouts store files as symlinks into the blob cache.
            tar.dereference = True
            for entry in entries:
                tar.add(entry, arcname=str(entry.relative_to(source)), recursive=False)
        populate_archive(archive, subsystem)


_ENV_TEMPLATE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: str) -> str:
    """Resolve ``${VAR}`` / ``${VAR:-default}`` against the container environment.

    Server credentials (FMP_API_KEY and friends) are declared as placeholders in
    the dataset and only ever resolved here, at run time.
    """
    return _ENV_TEMPLATE.sub(
        lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), value
    )


def configure_apps() -> None:
    config_path = WORLD_DATA_DIR / "mcp_config.json"
    if not config_path.exists():
        die(f"missing MCP config at {config_path}")
    config = json.loads(config_path.read_text())
    for server in config.get("mcpServers", {}).values():
        server["env"] = {k: expand_env(v) for k, v in (server.get("env") or {}).items()}
    servers = list(config.get("mcpServers", {}))
    if not servers:
        die("MCP config declares no servers")
    log(f"mounting {len(servers)} MCP server(s): {', '.join(servers)}")
    resp = httpx.post(f"{ENV_URL}/apps", json=config, timeout=APPS_TIMEOUT_SEC)
    if resp.status_code != 200:
        die(f"/apps failed: {resp.status_code} {resp.text[:500]}")
    log("MCP gateway mounted")


def capture_initial_snapshot() -> None:
    hooks = {}
    if SNAPSHOT_HOOKS.exists():
        hooks = {"pre_snapshot_hooks": json.loads(SNAPSHOT_HOOKS.read_text())}
    partial = INITIAL_SNAPSHOT.with_suffix(INITIAL_SNAPSHOT.suffix + ".partial")
    log("capturing initial snapshot")
    with httpx.stream(
        "POST", f"{ENV_URL}/data/snapshot", json=hooks or None, timeout=SNAPSHOT_TIMEOUT_SEC
    ) as resp:
        if resp.status_code != 200:
            die(f"initial snapshot failed: {resp.status_code}")
        with partial.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=65536):
                fh.write(chunk)
    # Publish atomically so the verifier never sees a truncated snapshot.
    partial.replace(INITIAL_SNAPSHOT)
    log(f"initial snapshot: {INITIAL_SNAPSHOT.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    wait_for_health()

    for subsystem, filename in SUBSYSTEMS.items():
        archive = WORLD_DATA_DIR / filename
        if archive.exists():
            populate_archive(archive, subsystem)
        elif subsystem == "filesystem":
            die(f"missing required world archive {archive}")

    # Task overlays land after the world seed; later writes win by design.
    for subsystem in SUBSYSTEMS:
        overlay = TASK_FILES_DIR / subsystem
        if overlay.is_dir():
            populate_dir(overlay, subsystem)

    configure_apps()

    if CAPTURE_INITIAL:
        capture_initial_snapshot()

    READY_MARKER.touch()
    log("world ready")


if __name__ == "__main__":
    main()
