import csv
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
        report.ensure_distinct_input_output(input_path, input_path)

    assert type(error.value) is report.ReportPathError


def test_rejects_output_hard_linked_to_input(tmp_path):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    input_path.write_bytes(b"original workbook")
    output_path.hardlink_to(input_path)

    with pytest.raises(ValueError, match="must be different") as error:
        report.ensure_distinct_input_output(input_path, output_path)

    assert type(error.value) is report.ReportPathError


def test_rejects_output_symlinked_to_input(tmp_path):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    input_path.write_bytes(b"original workbook")
    output_path.symlink_to(input_path)

    with pytest.raises(ValueError, match="must be different") as error:
        report.ensure_distinct_input_output(input_path, output_path)

    assert type(error.value) is report.ReportPathError


def test_writes_report_by_replacing_temp_file_in_destination_directory(tmp_path, monkeypatch):
    path = tmp_path / "failed.csv"
    replace_calls = []
    real_replace = os.replace

    def recording_replace(source, destination):
        replace_calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(report, "replace_file", recording_replace)

    write_failure_report(path, [])

    assert path.read_bytes() == (",".join(FAILURE_REPORT_COLUMNS) + "\n").encode()
    assert len(replace_calls) == 1
    temporary_path, destination = replace_calls[0]
    assert destination == path
    assert temporary_path.parent == path.parent
    assert temporary_path.name.startswith(".ab-report-")
    assert temporary_path.name.endswith(".tmp")


def test_resolves_destination_parent_once_before_symlink_retarget(
    tmp_path, monkeypatch
):
    real_a = tmp_path / "real-a"
    real_b = tmp_path / "real-b"
    real_a.mkdir()
    real_b.mkdir()
    parent_link = tmp_path / "report-parent"
    parent_link.symlink_to(real_a, target_is_directory=True)
    path = parent_link / "failed.csv"
    real_replace = os.replace

    def retargeting_replace(source, destination):
        parent_link.unlink()
        parent_link.symlink_to(real_b, target_is_directory=True)
        real_replace(source, destination)

    monkeypatch.setattr(report, "replace_file", retargeting_replace)

    write_failure_report(path, [])

    assert (real_a / "failed.csv").is_file()
    assert not (real_b / "failed.csv").exists()
    assert list(real_a.glob(".*.tmp")) == []
    assert list(real_b.glob(".*.tmp")) == []


def test_keeps_old_report_when_replace_fails_and_removes_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "failed.csv"
    old_report = b"previous report\n"
    path.write_bytes(old_report)

    def fail_replace(source, destination):
        raise OSError("replace blocked")

    monkeypatch.setattr(report, "replace_file", fail_replace)

    with pytest.raises(OSError, match="replace blocked"):
        write_failure_report(path, [])

    assert path.read_bytes() == old_report
    assert list(tmp_path.glob(".failed.csv.*.tmp")) == []


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
    assert list(tmp_path.glob(".failed.csv.*.tmp")) == []


def test_new_report_is_readable_by_the_user_who_owns_the_output_directory(tmp_path):
    path = tmp_path / "failed.csv"

    write_failure_report(path, [])

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
    assert list(tmp_path.glob(".*.tmp")) == []
