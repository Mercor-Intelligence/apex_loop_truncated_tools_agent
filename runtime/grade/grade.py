#!/usr/bin/env python3
"""Grade a Harbor trial with the Archipelago grading runner.

Reads the task's ``grading_config.json``, translates the Harbor-side artifacts
(ATIF trajectory, tar.gz snapshots) into what the runner expects, and writes the
reward files Harbor reads back.

Every failure path writes ``grading_error.json`` and exits non-zero: an exit 0
without a reward would score the trial 0.0 and hide the breakage.
"""

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from atif import atif_to_native  # noqa: E402

GRADING_CONFIG = Path("/tests/grading_config.json")
GOLDEN_DIR = Path("/tests/golden")
TRAJECTORY = Path("/logs/agent/trajectory.json")
INITIAL_SNAPSHOT = Path("/logs/world/initial_snapshot.tar.gz")
FINAL_SNAPSHOT = Path("/logs/world/final_snapshot.tar.gz")

VERIFIER_DIR = Path("/logs/verifier")
REWARD_TXT = VERIFIER_DIR / "reward.txt"
REWARD_JSON = VERIFIER_DIR / "reward.json"
GRADE_DETAILS = VERIFIER_DIR / "grade_details.json"
GRADING_ERROR = VERIFIER_DIR / "grading_error.json"

GRADING_PROJECT = Path(os.environ.get("GRADING_PROJECT", "/app/grading"))
GRADING_PYTHON = GRADING_PROJECT / ".venv/bin/python"


class GradingError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[grade] {msg}", flush=True)


def tar_gz_to_zip(path: Path) -> bytes:
    """The runner takes zip snapshots; the world streams tar.gz."""
    buf = io.BytesIO()
    with tarfile.open(path, "r:gz") as tar, zipfile.ZipFile(
        buf, "w", zipfile.ZIP_DEFLATED
    ) as zf:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if (fh := tar.extractfile(member)) is not None:
                zf.writestr(member.name, fh.read())
    return buf.getvalue()


def empty_zip() -> bytes:
    buf = io.BytesIO()
    zipfile.ZipFile(buf, "w").close()
    return buf.getvalue()


def snapshot_zip(path: Path, label: str) -> bytes:
    """Final-answer-only tasks capture no snapshots; anything else must have one.

    A missing snapshot on a file-graded task means the capture broke, which would
    otherwise grade as "the agent changed nothing" — a false zero.
    """
    if path.exists() and path.stat().st_size > 0:
        return tar_gz_to_zip(path)
    if Path("/tests/needs_snapshot").exists():
        raise GradingError(f"{label} snapshot missing or empty at {path}")
    return empty_zip()


def golden_zip() -> bytes | None:
    """Pack the shipped golden files into the shape --golden-snapshot expects."""
    if not GOLDEN_DIR.is_dir():
        return None
    files = [p for p in GOLDEN_DIR.rglob("*") if p.is_file()]
    if not files:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.writestr(str(path.relative_to(GOLDEN_DIR)), path.read_bytes())
    return buf.getvalue()


def judge_settings(config: dict[str, Any]) -> dict[str, Any]:
    settings = dict(config.get("grading_settings") or {})
    if override := os.environ.get("GRADING_MODEL"):
        settings["llm_judge_model"] = override
    if not settings.get("llm_judge_model"):
        raise GradingError("grading_settings.llm_judge_model is not set")

    extra = dict(settings.get("llm_judge_extra_args") or {})
    # Route the judge through the caller's proxy when one is configured.
    if key := os.environ.get("LITELLM_PROXY_API_KEY"):
        extra.setdefault("api_key", key)
    if base := os.environ.get("LITELLM_PROXY_API_BASE"):
        extra.setdefault("api_base", base)
    settings["llm_judge_extra_args"] = extra or None
    return settings


def run_grading(config: dict[str, Any], workdir: Path) -> dict[str, Any]:
    if not TRAJECTORY.exists():
        raise GradingError(f"no agent trajectory at {TRAJECTORY}")

    trajectory = atif_to_native(json.loads(TRAJECTORY.read_text()))
    if not trajectory.get("messages"):
        raise GradingError("agent trajectory has no messages")

    metadata = config.get("metadata") or {}
    files = {
        "trajectory.json": json.dumps(trajectory),
        "grading_settings.json": json.dumps(judge_settings(config)),
        "verifiers.json": json.dumps(config["verifiers"]),
        "eval_configs.json": json.dumps(config["eval_configs"]),
        "scoring_config.json": json.dumps(config["scoring_config"]),
    }
    for name, body in files.items():
        (workdir / name).write_text(body)

    (workdir / "initial.zip").write_bytes(snapshot_zip(INITIAL_SNAPSHOT, "initial"))
    (workdir / "final.zip").write_bytes(snapshot_zip(FINAL_SNAPSHOT, "final"))

    task_id = metadata.get("task_id", "task_unknown")
    command = [
        str(GRADING_PYTHON), "-m", "runner.main",
        "--grading-run-id", f"gr_{task_id}",
        "--trajectory-id", f"harbor_{task_id}",
        "--initial-snapshot", str(workdir / "initial.zip"),
        "--final-snapshot", str(workdir / "final.zip"),
        "--trajectory", str(workdir / "trajectory.json"),
        "--grading-settings", str(workdir / "grading_settings.json"),
        "--verifiers", str(workdir / "verifiers.json"),
        "--eval-configs", str(workdir / "eval_configs.json"),
        "--scoring-config", str(workdir / "scoring_config.json"),
        "--output", str(workdir / "grades.json"),
    ]
    if (golden := golden_zip()) is not None:
        (workdir / "golden.zip").write_bytes(golden)
        command += ["--golden-snapshot", str(workdir / "golden.zip")]

    log(f"running grading runner for {task_id}")
    result = subprocess.run(command, cwd=GRADING_PROJECT)
    if result.returncode != 0:
        raise GradingError(f"grading runner exited {result.returncode}")

    grades_path = workdir / "grades.json"
    if not grades_path.exists():
        raise GradingError("grading runner wrote no grades.json")
    return json.loads(grades_path.read_text())


def write_rewards(grades: dict[str, Any]) -> None:
    scoring = grades.get("scoring_results") or {}
    score = scoring.get("final_score")
    if score is None:
        raise GradingError("grading produced no final_score")

    rewards: dict[str, float] = {"reward": float(score)}
    for result in grades.get("verifier_results") or []:
        if (vid := result.get("verifier_id")) and result.get("score") is not None:
            rewards[vid] = float(result["score"])

    REWARD_JSON.write_text(json.dumps(rewards))
    REWARD_TXT.write_text(str(float(score)))
    GRADE_DETAILS.write_text(json.dumps(grades, indent=2))
    log(f"reward: {score}")


def main() -> None:
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    try:
        config = json.loads(GRADING_CONFIG.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            grades = run_grading(config, Path(tmp))
        write_rewards(grades)
    except Exception as exc:  # noqa: BLE001 - every failure must surface identically
        GRADING_ERROR.write_text(
            json.dumps({"grading_error": True, "detail": f"{type(exc).__name__}: {exc}"})
        )
        log(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
