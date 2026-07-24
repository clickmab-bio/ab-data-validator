from __future__ import annotations

import csv
import os
import tempfile
from os import replace as replace_file
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


class ReportPathError(ValueError):
    pass


def ensure_distinct_input_output(input_path: str | Path, output_path: str | Path) -> None:
    source = Path(input_path)
    destination = Path(output_path)
    try:
        same_file = source.samefile(destination)
    except FileNotFoundError:
        same_file = source.resolve(strict=False) == destination.resolve(strict=False)
    if same_file:
        raise ReportPathError("input and output paths must be different")


def write_failure_report(path: str | Path, failures: list[ValidationFailure]) -> None:
    destination = Path(path)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(
                handle,
                fieldnames=FAILURE_REPORT_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            for failure in failures:
                writer.writerow(_failure_to_row(failure))
        os.chmod(temporary_path, _report_file_mode(destination))
        replace_file(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _report_file_mode(destination: Path) -> int:
    try:
        return destination.stat().st_mode & 0o777
    except FileNotFoundError:
        return 0o644


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
