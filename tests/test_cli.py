import csv
import re
from datetime import datetime, timezone

import pytest

from ab_data_validator.alignment import AlignmentBackendError
from ab_data_validator.cli import _build_parser, _format_progress_message, main
from ab_data_validator.muscle import MuscleError
from ab_data_validator.numbering import NumberedResidue
from tests.xlsx_utils import write_xlsx


def make_chain(h1="A", h2="B", h3="C", *, stop=128):
    residues = []
    for position in range(1, stop + 1):
        residue = "F"
        if 27 <= position <= 38:
            residue = h1
        if 56 <= position <= 65:
            residue = h2
        if 105 <= position <= 117:
            residue = h3
        residues.append(NumberedResidue(position=position, insertion="", residue=residue))
    return residues


class FakeNumberer:
    def __init__(self, mapping):
        self.mapping = mapping

    def number(self, sequence_id, sequence, chain):
        return self.mapping[sequence]


class FixedIdentityAligner:
    def __init__(self, aligned_pair):
        self.aligned_pair = aligned_pair

    def align(self, cdr_name, candidate_cdr, positive_cdr):
        return self.aligned_pair


class FailingAligner:
    def align(self, cdr_name, candidate_cdr, positive_cdr):
        raise MuscleError("MUSCLE executable not found: muscle")


class FailingPairwiseAligner:
    def align(self, cdr_name, candidate_cdr, positive_cdr):
        raise AlignmentBackendError(
            "Pairwise alignment failed for CDRH3: no alignment"
        )


class CandidateAwareAligner:
    def align(self, cdr_name, candidate_cdr, positive_cdr):
        del cdr_name, positive_cdr
        if candidate_cdr.startswith("A"):
            return "AAAAAAAB", "AAAAAAAC"
        return "AAAAAAAB", "CCCCCCCC"


def write_csv(path, content):
    path.write_text(content, encoding="utf-8")


def write_input_xlsx(path, rows):
    write_xlsx(
        path,
        [
            ["序号", "抗体名称", "VH", "VL", "排序", "类型", "起始VH", "起始VL"],
            *rows,
        ],
    )


def read_failure_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def use_builtin_positive(monkeypatch, tmp_path, content="抗体名称,类型,抗体重链氨基酸,抗体轻链氨基酸\nPos1,VHH,pos_h,\n"):
    positive_path = tmp_path / "builtin_positive.csv"
    write_csv(positive_path, content)
    monkeypatch.setattr("ab_data_validator.cli.get_builtin_positive_csv_path", lambda: positive_path)
    return positive_path


def test_cli_formats_progress_message_in_beijing_time():
    utc_time = datetime(2026, 4, 28, 6, 57, 12, tzinfo=timezone.utc)

    message = _format_progress_message("Loading input: /data/input.xlsx", now=utc_time)

    assert message == "[2026-04-28 14:57:12 UTC+08:00] [ab-data-validator] Loading input: /data/input.xlsx"


def test_cli_validate_writes_failure_report_with_builtin_positive(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    rows = read_failure_rows(output_path)
    assert exit_code == 0
    assert rows[0]["reason_type"] == "high_cdr_identity"
    assert rows[0]["identity"] == "0.875"


def test_cli_defaults_output_next_to_input(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    assert exit_code == 0
    assert (tmp_path / "failed_reasons.csv").exists()


def test_cli_defaults_to_pairwise_backend():
    args = _build_parser().parse_args(["validate", "--input", "input.xlsx"])

    assert args.aligner == "pairwise"
    assert args.muscle_bin is None


def test_cli_accepts_manual_muscle_fallback():
    args = _build_parser().parse_args(
        [
            "validate",
            "--input",
            "input.xlsx",
            "--aligner",
            "muscle",
            "--muscle-bin",
            "muscle5",
        ]
    )

    assert args.aligner == "muscle"
    assert args.muscle_bin == "muscle5"


def test_cli_help_describes_configured_default_aligner(capsys):
    with pytest.raises(SystemExit) as error:
        _build_parser().parse_args(["validate", "--help"])

    assert error.value.code == 0
    assert "sequence alignment backend; default: pairwise" in capsys.readouterr().out


def test_cli_rejects_muscle_bin_in_pairwise_mode(monkeypatch):
    def fail_if_input_is_loaded(_):
        raise AssertionError("input must not be read for an invalid argument combination")

    monkeypatch.setattr("ab_data_validator.cli.load_input_file", fail_if_input_is_loaded)

    with pytest.raises(SystemExit) as error:
        main(
            [
                "validate",
                "--input",
                "input.xlsx",
                "--muscle-bin",
                "muscle5",
            ]
        )

    assert error.value.code == 2


def test_cli_rejects_input_and_output_at_same_path_before_reading_or_constructing_aligner(
    tmp_path, capsys, monkeypatch
):
    input_path = tmp_path / "input.xlsx"
    original_input = b"original workbook"
    input_path.write_bytes(original_input)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("path validation must run first")

    monkeypatch.setattr("ab_data_validator.cli.load_input_file", fail_if_called)
    monkeypatch.setattr("ab_data_validator.cli.create_production_aligner", fail_if_called)

    exit_code = main(
        ["validate", "--input", str(input_path), "--output", str(input_path)]
    )

    assert exit_code == 2
    assert "must be different" in capsys.readouterr().err
    assert input_path.read_bytes() == original_input


def test_cli_rejects_output_hard_linked_to_input_before_reading(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    input_path.write_bytes(b"original workbook")
    output_path.hardlink_to(input_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("path validation must run first")

    monkeypatch.setattr("ab_data_validator.cli.load_input_file", fail_if_called)
    monkeypatch.setattr("ab_data_validator.cli.create_production_aligner", fail_if_called)

    exit_code = main(
        ["validate", "--input", str(input_path), "--output", str(output_path)]
    )

    assert exit_code == 2
    assert "must be different" in capsys.readouterr().err


def test_cli_constructs_and_logs_pairwise_default(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)
    captured_factory_args = {}
    fixed_aligner = FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC"))

    def create_aligner(backend, *, muscle_bin):
        captured_factory_args.update(backend=backend, muscle_bin=muscle_bin)
        return fixed_aligner

    monkeypatch.setattr("ab_data_validator.cli.create_production_aligner", create_aligner)
    monkeypatch.setattr(
        "ab_data_validator.cli.describe_production_aligner",
        lambda backend, *, muscle_bin: "aligner=pairwise biopython=1.87 matrix=BLOSUM62 gap_open=11 gap_extend=1",
    )

    exit_code = main(
        ["validate", "--input", str(input_path), "--output", str(output_path)],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
    )

    assert exit_code == 0
    assert captured_factory_args == {"backend": "pairwise", "muscle_bin": "muscle"}
    assert (
        "Using aligner=pairwise biopython=1.87 matrix=BLOSUM62 gap_open=11 gap_extend=1"
        in capsys.readouterr().err
    )


def test_cli_logs_injected_aligner_without_constructing_default(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    def fail_if_default_is_constructed(*args, **kwargs):
        raise AssertionError("injected aligner must bypass default construction")

    monkeypatch.setattr("ab_data_validator.cli.create_production_aligner", fail_if_default_is_constructed)

    exit_code = main(
        ["validate", "--input", str(input_path), "--output", str(output_path)],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    assert exit_code == 0
    assert "Using injected aligner" in capsys.readouterr().err


def test_cli_constructs_manual_muscle_fallback(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)
    captured_factory_args = {}

    def create_aligner(backend, *, muscle_bin):
        captured_factory_args.update(backend=backend, muscle_bin=muscle_bin)
        return FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC"))

    monkeypatch.setattr("ab_data_validator.cli.create_production_aligner", create_aligner)
    monkeypatch.setattr(
        "ab_data_validator.cli.describe_production_aligner",
        lambda backend, *, muscle_bin: f"aligner={backend} executable={muscle_bin}",
    )

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--aligner",
            "muscle",
            "--muscle-bin",
            "muscle5",
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
    )

    assert exit_code == 0
    assert captured_factory_args == {"backend": "muscle", "muscle_bin": "muscle5"}
    assert "Using aligner=muscle executable=muscle5" in capsys.readouterr().err


def test_cli_excel_input_adds_parent_references_to_current_run_positive_set(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", "runtime_pos_h", None]])
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        numberer=FakeNumberer(
            {
                "ab_h": make_chain(),
                "pos_h": make_chain(),
                "runtime_pos_h": make_chain(),
            }
        ),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    rows = read_failure_rows(output_path)
    positive_names = {row["positive_name"] for row in rows}
    assert exit_code == 0
    assert positive_names == {"Pos1", "Ab1__parent_reference"}


def test_cli_rejects_user_supplied_positive_argument(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    with pytest.raises(SystemExit):
        main(
            [
                "validate",
                "--input",
                str(input_path),
                "--positive",
                str(tmp_path / "other_positive.csv"),
                "--output",
                str(output_path),
            ],
            numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
            aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
        )


def test_cli_custom_threshold_changes_identity_filtering(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--identity-threshold",
            "0.9",
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    assert exit_code == 0
    assert read_failure_rows(output_path) == []


def test_cli_logs_custom_identity_threshold(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--identity-threshold",
            "0.75",
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    assert exit_code == 0
    assert "Using identity threshold 0.75" in capsys.readouterr().err


def test_cli_passes_resolved_worker_count_to_validator(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)
    captured = {}

    class RecordingValidator:
        def __init__(self, *, numberer, aligner, identity_threshold, max_workers, progress_logger):
            del numberer, aligner, identity_threshold
            captured["max_workers"] = max_workers
            captured["has_progress_logger"] = progress_logger is not None

        def validate(self, candidates, positives):
            captured["candidate_count"] = len(candidates)
            captured["positive_count"] = len(positives)
            return []

    monkeypatch.setattr("ab_data_validator.cli.resolve_worker_count", lambda requested: 6)
    monkeypatch.setattr("ab_data_validator.cli.Validator", RecordingValidator)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--workers",
            "0",
        ],
        numberer=FakeNumberer({}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    assert exit_code == 0
    assert captured == {
        "max_workers": 6,
        "has_progress_logger": True,
        "candidate_count": 1,
        "positive_count": 1,
    }


def test_cli_rejects_negative_worker_count(tmp_path):
    input_path = tmp_path / "input.xlsx"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])

    with pytest.raises(SystemExit):
        main(["validate", "--input", str(input_path), "--workers", "-1"])


def test_cli_prints_summary_after_successful_validation(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(
        input_path,
        [
            [1, "FailedAb", "fail_h", "n/a", 1, "优化改造", None, None],
            [2, "PassedAb", "pass_h", "n/a", 2, "优化改造", None, None],
        ],
    )
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        numberer=FakeNumberer(
            {
                "fail_h": make_chain(h1="A", h2="B", h3="C"),
                "pass_h": make_chain(h1="D", h2="E", h3="G"),
                "pos_h": make_chain(),
            }
        ),
        aligner=CandidateAwareAligner(),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Validation summary" in captured.out
    assert "Total antibodies: 2" in captured.out
    assert "Passed: 1" in captured.out
    assert "Failed: 1" in captured.out
    assert f"Failure report: {output_path}" in captured.out


def test_cli_writes_timestamped_progress_logs_to_stderr(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert re.search(
        r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC\+08:00\] "
        r"\[ab-data-validator\] Loading input:",
        captured.err,
    )
    assert "[ab-data-validator] Loaded 1 candidates and 0 parent references" in captured.err
    assert "[ab-data-validator] Loaded 1 built-in positive references" in captured.err
    assert "[ab-data-validator] Using " in captured.err
    assert "[ab-data-validator] Numbering positive references" in captured.err
    assert "[ab-data-validator] Numbering candidate antibodies" in captured.err
    assert "[ab-data-validator] Comparing candidate CDRs to positive references" in captured.err
    assert "[ab-data-validator] Writing failure report:" in captured.err
    assert "Validation summary" in captured.out
    assert "Validation summary" not in captured.err


def test_cli_returns_nonzero_for_invalid_builtin_positive_reference(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path, content="抗体名称,类型,抗体重链氨基酸,抗体轻链氨基酸\nBadPos,VHH,bad_pos_h,\n")

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "bad_pos_h": make_chain()[1:]}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "BadPos" in captured.err


def test_cli_returns_nonzero_for_alignment_runtime_error(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FailingAligner(),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "MUSCLE executable not found" in captured.err


def test_cli_returns_nonzero_for_alignment_backend_error(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FailingPairwiseAligner(),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Pairwise alignment failed for CDRH3: no alignment" in captured.err


def test_cli_returns_nonzero_when_output_file_cannot_be_written(tmp_path, capsys, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "failed.csv"
    write_input_xlsx(input_path, [[1, "Ab1", "ab_h", "n/a", 1, "优化改造", None, None]])
    use_builtin_positive(monkeypatch, tmp_path)

    def fail_write(path, failures):
        raise PermissionError("permission denied")

    monkeypatch.setattr("ab_data_validator.cli.write_failure_report", fail_write)

    exit_code = main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FixedIdentityAligner(("AAAAAAAB", "AAAAAAAC")),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "permission denied" in captured.err
