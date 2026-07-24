import csv
import errno
import os
import stat
from pathlib import Path

import pytest

import ab_data_validator.report as report
from ab_data_validator.models import InputType, ValidationFailure
from ab_data_validator.report import FAILURE_REPORT_COLUMNS, write_failure_report


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def assert_no_temporary_reports(*directories):
    for directory in directories:
        assert list(directory.glob(".ab-report-*.tmp")) == []


def assert_file_descriptor_closed(file_descriptor):
    with pytest.raises(OSError) as error:
        os.fstat(file_descriptor)
    assert error.value.errno == errno.EBADF


def test_writes_header_when_no_failures(tmp_path):
    path = tmp_path / "failed.csv"

    write_failure_report(path, [])

    assert path.read_text(encoding="utf-8").strip() == ",".join(FAILURE_REPORT_COLUMNS)


def test_writes_lf_line_endings(tmp_path):
    path = tmp_path / "failed.csv"

    write_failure_report(path, [])

    report = path.read_bytes()
    assert b"\n" in report
    assert b"\r\n" not in report


def test_writes_failure_rows(tmp_path):
    path = tmp_path / "failed.csv"
    failures = [
        ValidationFailure(
            name="Ab1",
            input_type=InputType.FULL_ANTIBODY,
            reason_type="anarci_failed",
            chain="VH",
            details="VH cannot be numbered by ANARCI",
        ),
        ValidationFailure(
            name="Ab1",
            input_type=InputType.FULL_ANTIBODY,
            reason_type="high_cdr_identity",
            chain="VH",
            cdr="CDRH3",
            positive_name="PositiveA",
            identity=0.9231,
            threshold=0.8,
            details="CDRH3 identity to PositiveA is 0.9231 >= 0.8",
        ),
    ]

    write_failure_report(path, failures)

    rows = read_rows(path)
    assert rows[0]["name"] == "Ab1"
    assert rows[0]["input_type"] == "full_antibody"
    assert rows[0]["passed"] == "false"
    assert rows[0]["reason_type"] == "anarci_failed"
    assert rows[0]["chain"] == "VH"
    assert rows[1]["cdr"] == "CDRH3"
    assert rows[1]["positive_name"] == "PositiveA"
    assert rows[1]["identity"] == "0.9231"
    assert rows[1]["threshold"] == "0.8"


def test_rejects_input_and_output_at_same_path(tmp_path):
    input_path = tmp_path / "input.xlsx"
    input_path.write_bytes(b"original workbook")

    with pytest.raises(ValueError, match="must be different") as error:
        report.prepare_report_destination(input_path, input_path)

    assert type(error.value) is report.ReportPathError


def test_rejects_output_hard_linked_to_input(tmp_path):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    input_path.write_bytes(b"original workbook")
    output_path.hardlink_to(input_path)

    with pytest.raises(ValueError, match="must be different") as error:
        report.prepare_report_destination(input_path, output_path)

    assert type(error.value) is report.ReportPathError


def test_rejects_output_symlinked_to_input(tmp_path):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    input_path.write_bytes(b"original workbook")
    output_path.symlink_to(input_path)

    with pytest.raises(ValueError, match="must be different") as error:
        report.prepare_report_destination(input_path, output_path)

    assert type(error.value) is report.ReportPathError


def test_prepared_destination_keeps_fixed_canonical_parent(
    tmp_path
):
    input_dir = tmp_path / "input"
    reports = tmp_path / "reports"
    input_dir.mkdir()
    reports.mkdir()
    input_path = input_dir / "input.xlsx"
    original_input = b"original workbook"
    input_path.write_bytes(original_input)
    output_parent = tmp_path / "output-parent"
    output_parent.symlink_to(reports, target_is_directory=True)
    requested_output = output_parent / "input.xlsx"

    prepared = report.prepare_report_destination(
        input_path,
        requested_output,
    )
    with prepared as destination:
        output_parent.unlink()
        output_parent.symlink_to(input_dir, target_is_directory=True)
        write_failure_report(destination, [])

    assert prepared.path == reports / "input.xlsx"
    assert input_path.read_bytes() == original_input
    assert (reports / "input.xlsx").is_file()
    assert_no_temporary_reports(input_dir, reports)


def test_writes_report_by_replacing_temp_file_in_destination_directory(tmp_path, monkeypatch):
    path = tmp_path / "failed.csv"
    replace_calls = []
    real_replace = os.replace

    def recording_replace(source, destination, **kwargs):
        replace_calls.append((source, destination, kwargs))
        real_replace(source, destination, **kwargs)

    monkeypatch.setattr(report, "replace_file", recording_replace)

    write_failure_report(path, [])

    assert path.read_bytes() == (",".join(FAILURE_REPORT_COLUMNS) + "\n").encode()
    assert len(replace_calls) == 1
    temporary_name, destination_name, replace_options = replace_calls[0]
    assert destination_name == path.name
    assert temporary_name.startswith(".ab-report-")
    assert temporary_name.endswith(".tmp")
    assert replace_options["src_dir_fd"] == replace_options["dst_dir_fd"]


def test_writer_uses_directory_fd_when_parent_is_replaced_after_temp_creation(
    tmp_path, monkeypatch
):
    report_parent = tmp_path / "reports"
    moved_parent = tmp_path / "reports-moved"
    replacement_target = tmp_path / "replacement-target"
    report_parent.mkdir()
    replacement_target.mkdir()
    path = report_parent / "failed.csv"
    real_replace = os.replace

    def replacing_parent_then_replace(source, destination, **kwargs):
        report_parent.rename(moved_parent)
        report_parent.symlink_to(
            replacement_target,
            target_is_directory=True,
        )
        real_replace(source, destination, **kwargs)

    monkeypatch.setattr(
        report,
        "replace_file",
        replacing_parent_then_replace,
    )

    write_failure_report(path, [])

    assert (moved_parent / "failed.csv").is_file()
    assert not (replacement_target / "failed.csv").exists()
    assert_no_temporary_reports(moved_parent, replacement_target)


def test_keeps_old_report_when_replace_fails_and_removes_temp_file(tmp_path, monkeypatch):
    report_parent = tmp_path / "reports"
    moved_parent = tmp_path / "reports-moved"
    replacement_target = tmp_path / "replacement-target"
    report_parent.mkdir()
    replacement_target.mkdir()
    path = report_parent / "failed.csv"
    old_report = b"previous report\n"
    path.write_bytes(old_report)

    def fail_replace(source, destination, **kwargs):
        del source, destination, kwargs
        report_parent.rename(moved_parent)
        report_parent.symlink_to(
            replacement_target,
            target_is_directory=True,
        )
        raise OSError("replace blocked")

    monkeypatch.setattr(report, "replace_file", fail_replace)

    with pytest.raises(OSError, match="replace blocked"):
        write_failure_report(path, [])

    assert (moved_parent / "failed.csv").read_bytes() == old_report
    assert_no_temporary_reports(moved_parent, replacement_target)


def test_keeps_old_report_when_failure_serialization_fails_and_removes_temp_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "failed.csv"
    old_report = b"previous report\n"
    path.write_bytes(old_report)
    failure = ValidationFailure(
        name="Ab1",
        input_type=InputType.FULL_ANTIBODY,
        reason_type="anarci_failed",
        chain="VH",
        details="VH cannot be numbered by ANARCI",
    )

    def fail_serialization(value):
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(report, "_failure_to_row", fail_serialization)

    with pytest.raises(RuntimeError, match="serialization failed"):
        write_failure_report(path, [failure])

    assert path.read_bytes() == old_report
    assert_no_temporary_reports(tmp_path)


def test_new_report_is_readable_by_the_user_who_owns_the_output_directory(tmp_path):
    path = tmp_path / "failed.csv"

    previous_umask = os.umask(0o022)
    try:
        write_failure_report(path, [])
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_new_report_mode_respects_restrictive_umask(tmp_path):
    path = tmp_path / "failed.csv"
    previous_umask = os.umask(0o077)
    try:
        write_failure_report(path, [])
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_replacing_existing_report_preserves_its_mode(tmp_path):
    path = tmp_path / "failed.csv"
    path.write_text("previous report\n", encoding="utf-8")
    path.chmod(0o640)

    write_failure_report(path, [])

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_existing_mode_is_applied_with_fchmod_while_temp_fd_is_open(
    tmp_path, monkeypatch
):
    path = tmp_path / "failed.csv"
    path.write_text("previous report\n", encoding="utf-8")
    path.chmod(0o640)
    real_fchmod = os.fchmod
    fchmod_modes = []

    def recording_fchmod(file_descriptor, mode):
        os.fstat(file_descriptor)
        fchmod_modes.append(stat.S_IMODE(mode))
        real_fchmod(file_descriptor, mode)

    def forbidden_path_chmod(*args, **kwargs):
        raise AssertionError("temporary paths must not be chmodded after close")

    def forbidden_os_chmod(*args, **kwargs):
        raise AssertionError("temporary paths must not be chmodded after close")

    monkeypatch.setattr(report.os, "fchmod", recording_fchmod)
    monkeypatch.setattr(report.os, "chmod", forbidden_os_chmod)
    monkeypatch.setattr(Path, "chmod", forbidden_path_chmod)

    write_failure_report(path, [])

    assert fchmod_modes == [0o640]
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_writes_report_with_legal_name_near_name_max(tmp_path):
    suffix = ".csv"
    name_max = os.pathconf(tmp_path, "PC_NAME_MAX")
    stem_length = min(240, name_max - len(suffix))
    path = tmp_path / ("a" * stem_length + suffix)

    write_failure_report(path, [])

    assert path.read_bytes() == (
        ",".join(FAILURE_REPORT_COLUMNS) + "\n"
    ).encode()
    assert_no_temporary_reports(tmp_path)


def test_prepared_destination_closes_directory_fd_after_success(tmp_path):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    input_path.write_bytes(b"input")
    prepared = report.prepare_report_destination(
        input_path,
        output_path,
    )
    directory_fd = prepared.directory_fd

    with prepared as destination:
        write_failure_report(destination, [])

    assert output_path.is_file()
    assert_file_descriptor_closed(directory_fd)


def test_prepared_destination_closes_directory_fd_after_exception(tmp_path):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    input_path.write_bytes(b"input")
    prepared = report.prepare_report_destination(
        input_path,
        output_path,
    )
    directory_fd = prepared.directory_fd

    with pytest.raises(RuntimeError, match="validation failed"):
        with prepared:
            raise RuntimeError("validation failed")

    assert_file_descriptor_closed(directory_fd)


def test_prepare_rejects_parent_changed_between_stat_and_directory_open(
    tmp_path,
    monkeypatch,
):
    input_dir = tmp_path / "input"
    reports = tmp_path / "reports"
    moved_reports = tmp_path / "reports-moved"
    input_dir.mkdir()
    reports.mkdir()
    input_path = input_dir / "input.xlsx"
    input_path.write_bytes(b"input")
    output_path = reports / "failed.csv"
    real_open = os.open
    changed_parent = False

    def open_after_parent_replacement(
        path,
        flags,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        nonlocal changed_parent
        if not changed_parent and flags & os.O_DIRECTORY:
            changed_parent = True
            reports.rename(moved_reports)
            reports.symlink_to(input_dir, target_is_directory=True)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(report.os, "open", open_after_parent_replacement)

    with pytest.raises(
        report.ReportPathError,
        match="changed while opening",
    ):
        report.prepare_report_destination(input_path, output_path)
