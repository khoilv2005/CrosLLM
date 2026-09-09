"""Regenerate development harness runners from the canonical Docker template."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dataset.tools.extract_all_artifacts import (
    DEV_HARNESS_SUITES,
    LINEAGE_SPECS,
    render_harness_runner,
)


HARNESS_DIR = ROOT / "dataset" / "harness"


def main() -> int:
    for lineage_id in sorted(DEV_HARNESS_SUITES):
        runner_path = HARNESS_DIR / lineage_id / "normal_workflow_test.py"
        runner_path.write_text(
            render_harness_runner(lineage_id, LINEAGE_SPECS[lineage_id]),
            encoding="utf-8",
        )
        print(f"Updated {lineage_id} normal_workflow_test.py")
    print("All development runners use the canonical pinned Docker argv boundary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
