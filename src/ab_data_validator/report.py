from __future__ import annotations

import csv
import os
import secrets
import stat
from dataclasses import dataclass, field
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


@dataclass
class ReportDestination:
    path: Path
    display_path: Path
    directory_fd: int
    filename: str
    _closed: bool = field(default=False, init=False, repr=False)

    def __enter__(self) -> ReportDestination:
        if self._closed:
            raise ValueError("report destination is closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        del exc_value, traceback
        try:
            self.close()
        except OSError:
            if exc_type is None:
                raise
        return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self.directory_fd)


def prepare_report_destination(
    input_path: str | Path,
    output_path: str | Path,
) -> ReportDestination:
    destination = _open_report_destination(output_path)
    try:
        source_stat = os.stat(input_path, follow_symlinks=True)
        try:
            destination_stat = os.stat(
                destination.filename,
                dir_fd=destination.directory_fd,
                follow_symlinks=True,
            )
        except FileNotFoundError:
            same_file = (
                Path(input_path).resolve(strict=False)
                == destination.path
            )
        else:
            same_file = os.path.samestat(
                source_stat,
                destination_stat,
            )
        if same_file:
            raise ReportPathError(
                "input and output paths must be different"
            )
        return destination
    except BaseException:
        _close_without_masking(destination)
        raise


def write_failure_report(
    path: str | Path | ReportDestination,
    failures: list[ValidationFailure],
) -> None:
    if isinstance(path, ReportDestination):
        _write_failure_report(path, failures)
        return
    with _open_report_destination(path) as destination:
        _write_failure_report(destination, failures)


def _write_failure_report(
    destination: ReportDestination,
    failures: list[ValidationFailure],
) -> None:
    existing_mode = _existing_report_mode(destination)
    temporary_name: str | None = None
    file_descriptor: int | None = None
    try:
        file_descriptor, temporary_name = _open_temporary_report(
            destination
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
        replace_file(
            temporary_name,
            destination.filename,
            src_dir_fd=destination.directory_fd,
            dst_dir_fd=destination.directory_fd,
        )
        temporary_name = None
    finally:
        if file_descriptor is not None:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if temporary_name is not None:
            try:
                os.unlink(
                    temporary_name,
                    dir_fd=destination.directory_fd,
                )
            except OSError:
                pass


def _open_report_destination(
    path: str | Path,
) -> ReportDestination:
    requested_path = Path(path)
    parent_stat = os.stat(
        requested_path.parent,
        follow_symlinks=True,
    )
    resolved_parent = requested_path.parent.resolve(strict=True)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory_fd = os.open(resolved_parent, flags)
    try:
        if not os.path.samestat(parent_stat, os.fstat(directory_fd)):
            raise ReportPathError(
                "output directory changed while opening"
            )
        return ReportDestination(
            path=resolved_parent / requested_path.name,
            display_path=requested_path,
            directory_fd=directory_fd,
            filename=requested_path.name,
        )
    except BaseException:
        try:
            os.close(directory_fd)
        except OSError:
            pass
        raise


def _close_without_masking(destination: ReportDestination) -> None:
    try:
        destination.close()
    except OSError:
        pass


def _existing_report_mode(
    destination: ReportDestination,
) -> int | None:
    try:
        destination_stat = os.stat(
            destination.filename,
            dir_fd=destination.directory_fd,
            follow_symlinks=True,
        )
    except FileNotFoundError:
        return None
    return stat.S_IMODE(destination_stat.st_mode)


def _open_temporary_report(
    destination: ReportDestination,
) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for _ in range(TEMPORARY_REPORT_ATTEMPTS):
        temporary_name = (
            f".ab-report-{secrets.token_hex(8)}.tmp"
        )
        try:
            return (
                os.open(
                    temporary_name,
                    flags,
                    0o666,
                    dir_fd=destination.directory_fd,
                ),
                temporary_name,
            )
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
