from __future__ import annotations

import csv
from pathlib import Path

from ab_data_validator.models import ValidationFailure


FAILURE_REPORT_COLUMNS = [
    "name",
    "input_type",
    "passed",
    "reason_type",
    "chain",
    "cdr",
    "positive_name",
    "identity",
    "threshold",
    "details",
]


def write_failure_report(path: str | Path, failures: list[ValidationFailure]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FAILURE_REPORT_COLUMNS)
        writer.writeheader()
        for failure in failures:
            writer.writerow(_failure_to_row(failure))


def _failure_to_row(failure: ValidationFailure) -> dict[str, str]:
    return {
        "name": failure.name,
        "input_type": failure.input_type.value,
        "passed": "false",
        "reason_type": failure.reason_type,
        "chain": failure.chain,
        "cdr": failure.cdr,
        "positive_name": failure.positive_name,
        "identity": "" if failure.identity is None else f"{failure.identity:g}",
        "threshold": "" if failure.threshold is None else f"{failure.threshold:g}",
        "details": failure.details,
    }
