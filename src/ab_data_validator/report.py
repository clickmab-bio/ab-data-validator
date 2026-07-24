from __future__ import annotations

import csv
import os
import secrets
import stat
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


TEMPORARY_REPORT_ATTEMPTS = 16


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
    resolved_parent = destination.parent.resolve(strict=True)
    resolved_destination = resolved_parent / destination.name
    existing_mode = _existing_report_mode(resolved_destination)
    temporary_path: Path | None = None
    file_descriptor: int | None = None
    try:
        file_descriptor, temporary_path = _open_temporary_report(
            resolved_parent
        )
        handle = os.fdopen(
            file_descriptor,
            mode="w",
            newline="",
            encoding="utf-8",
        )
        file_descriptor = None
        with handle:
            if existing_mode is not None:
                os.fchmod(handle.fileno(), existing_mode)
            writer = csv.DictWriter(
                handle,
                fieldnames=FAILURE_REPORT_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            for failure in failures:
                writer.writerow(_failure_to_row(failure))
            handle.flush()
        replace_file(temporary_path, resolved_destination)
        temporary_path = None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _existing_report_mode(destination: Path) -> int | None:
    try:
        return stat.S_IMODE(destination.stat().st_mode)
    except FileNotFoundError:
        return None


def _open_temporary_report(parent: Path) -> tuple[int, Path]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for _ in range(TEMPORARY_REPORT_ATTEMPTS):
        temporary_path = (
            parent / f".ab-report-{secrets.token_hex(8)}.tmp"
        )
        try:
            return os.open(temporary_path, flags, 0o666), temporary_path
        except FileExistsError:
            continue
    raise FileExistsError("could not create a unique temporary report")


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
