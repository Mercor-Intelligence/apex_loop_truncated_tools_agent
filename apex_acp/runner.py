"""Run the reference CLI in the adapter's Python environment."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.path.insert(0, str(ROOT / "apex_loop_truncated_tools_agent" / "runner_src"))
    from runner_cli import main as run

    run()


if __name__ == "__main__":
    main()
