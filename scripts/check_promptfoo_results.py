#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def type_name(value: Any) -> str:
    return type(value).__name__


def parse_http_status(value: Any) -> tuple[int | None, str | None]:
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped), None
        return None, "status_not_numeric_string"
    return None, f"status_invalid_type:{type_name(value)}"


def main() -> int:
    args = parse_args()
    results_path = Path(args.results_path)
    if not results_path.is_file():
        print(f"promptfoo_gate_error missing_results_file path={results_path}")
        return 1

    try:
        with results_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        print(
            "promptfoo_gate_error invalid_json "
            f"path={results_path} line={exc.lineno} col={exc.colno} msg={exc.msg}"
        )
        return 1
    except OSError as exc:
        print(
            "promptfoo_gate_error unreadable_results_file "
            f"path={results_path} err={exc.__class__.__name__}"
        )
        return 1

    if not isinstance(payload, dict):
        print(
            "promptfoo_gate_error schema_mismatch "
            f"path={results_path} field=root expected=dict actual={type_name(payload)}"
        )
        return 1

    results_obj = payload.get("results")
    if not isinstance(results_obj, dict):
        print(
            "promptfoo_gate_error schema_mismatch "
            f"path={results_path} field=results expected=dict actual={type_name(results_obj)}"
        )
        return 1

    result_rows = results_obj.get("results")
    if not isinstance(result_rows, list):
        print(
            "promptfoo_gate_error schema_mismatch "
            f"path={results_path} field=results.results expected=list actual={type_name(result_rows)}"
        )
        return 1

    total = len(result_rows)
    if total == 0:
        print("promptfoo_gate_error zero_results_rows")
        return 1

    failed = 0
    non_200 = 0
    row_schema_errors = 0
    status_schema_errors = 0

    for index, row in enumerate(result_rows):
        if not isinstance(row, dict):
            row_schema_errors += 1
            print(
                "promptfoo_gate_row_error "
                f"index={index} reason=row_not_object actual={type_name(row)}"
            )
            continue

        success = row.get("success")
        grading = row.get("gradingResult")
        if not isinstance(grading, dict):
            row_schema_errors += 1
            print(
                "promptfoo_gate_row_error "
                f"index={index} reason=gradingResult_not_object actual={type_name(grading)}"
            )
        else:
            grading_pass = grading.get("pass")
            if success is not True or grading_pass is not True:
                failed += 1

        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            status_schema_errors += 1
            print(
                "promptfoo_gate_row_error "
                f"index={index} reason=metadata_not_object actual={type_name(metadata)}"
            )
            continue

        http_obj = metadata.get("http")
        if not isinstance(http_obj, dict):
            status_schema_errors += 1
            print(
                "promptfoo_gate_row_error "
                f"index={index} reason=http_not_object actual={type_name(http_obj)}"
            )
            continue

        status_value = http_obj.get("status")
        if status_value is None:
            status_schema_errors += 1
            print(
                "promptfoo_gate_row_error "
                f"index={index} reason=missing_http_status"
            )
            continue

        parsed_status, status_error = parse_http_status(status_value)
        if status_error is not None:
            status_schema_errors += 1
            print(
                "promptfoo_gate_row_error "
                f"index={index} reason={status_error} actual={type_name(status_value)}"
            )
            continue

        if parsed_status != 200:
            non_200 += 1

    print(
        "promptfoo_gate_summary "
        f"total={total} "
        f"failed={failed} "
        f"non_200={non_200} "
        f"row_schema_errors={row_schema_errors} "
        f"status_schema_errors={status_schema_errors}"
    )

    if row_schema_errors > 0 or status_schema_errors > 0:
        print("promptfoo_gate_error schema_mismatch_detected")
        return 1
    if failed > 0:
        print("promptfoo_gate_error assertion_failures_detected")
        return 1
    if non_200 > 0:
        print("promptfoo_gate_error non_200_responses_detected")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
