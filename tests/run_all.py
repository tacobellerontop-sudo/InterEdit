#!/usr/bin/env python3
"""Run every regression script:  python tests/run_all.py  (from repo root)."""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_autoformat", "test_qol", "test_qol2", "test_session",
          "test_tables", "test_office", "test_gutter", "test_consumer"]


def main():
    failed = []
    for suite in SUITES:
        print(f"===== {suite} =====")
        proc = subprocess.run([sys.executable, f"{suite}.py"], cwd=HERE)
        if proc.returncode != 0:
            failed.append(suite)
    if failed:
        print(f"\nFAILED: {failed}")
        return 1
    print("\nALL SUITES GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
