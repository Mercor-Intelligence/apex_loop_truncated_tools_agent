"""Download a Hugging Face source dataset."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

from apex11.runtime_utils import REPO_ID, inventory


def download_dataset(
    repo_id: str, output: Path, token: str | None = None
) -> dict[str, object]:
    api = HfApi(token=token)
    info = api.repo_info(repo_id=repo_id, repo_type="dataset")
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        local_dir=output,
        token=token,
    )
    report = inventory(output)
    report.update(
        {"repo_id": repo_id, "repo_type": "dataset", "private": bool(info.private)}
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not REPO_ID.fullmatch(args.repo_id):
        sys.exit("--repo-id must be in owner/name form")
    token = os.environ.get("HF_TOKEN", "").strip() or None
    try:
        report = download_dataset(args.repo_id, args.output.resolve(), token)
    except (RuntimeError, ValueError) as exc:
        sys.exit(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
