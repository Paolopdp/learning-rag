#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate promptfoo results gate conditions."
    )
    parser.add_argument(
        "--results-path",
        default="artifacts/promptfoo/results.json",
        help="Path to promptfoo JSON results artifact.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results_path = Path(args.results_path)
    if not results_path.is_file():
        print(f"promptfoo_gate_error missing_results_file path={results_path}")
        return 1

    with results_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    result_rows = payload.get("results", {}).get("results", [])
    total = len(result_rows)
    if total == 0:
        print("promptfoo_gate_error zero_results_rows")
        return 1

    failed = 0
    non_200 = 0
    for row in result_rows:
        passed = (
            row.get("success") is True
            and row.get("gradingResult", {}).get("pass") is True
        )
        if not passed:
            failed += 1

        status = row.get("metadata", {}).get("http", {}).get("status")
        if status != 200:
            non_200 += 1

    print(
        f"promptfoo_gate_summary total={total} failed={failed} non_200={non_200}"
    )
    if failed > 0:
        return 1
    if non_200 > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
