"""Small shared helpers used by the download and validation path."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any


REPO_ID = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")
REQUIRED_DATASET_FILES = (
    "tasks_and_rubrics.json",
    "world_descriptions.json",
    "metadata.json",
)
IGNORED_LOCAL_PARTS = {".cache", ".git", ".venv", "__pycache__"}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def valid_world_zip(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return bool(archive.namelist()) and archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def payload_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_LOCAL_PARTS for part in path.relative_to(root).parts)
    )


def inventory(root: Path) -> dict[str, Any]:
    missing = [name for name in REQUIRED_DATASET_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError(f"dataset is missing required file(s): {', '.join(missing)}")
    files = payload_files(root)
    transient = [path for path in files if path.name.endswith((".part", ".tmp"))]
    if transient:
        names = ", ".join(str(path.relative_to(root)) for path in transient[:5])
        raise ValueError(f"dataset contains incomplete temporary file(s): {names}")
    return {
        "root": str(root),
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "largest_files": [
            {"path": str(path.relative_to(root)), "bytes": path.stat().st_size}
            for path in sorted(files, key=lambda item: item.stat().st_size, reverse=True)[:10]
        ],
    }
