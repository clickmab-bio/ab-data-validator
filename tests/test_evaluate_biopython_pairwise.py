from __future__ import annotations

import csv
import hashlib
import json
import os
import stat
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from ab_data_validator.models import InputType
from ab_data_validator.report import ReportPathError
from ab_data_validator.validation import IdentityComparison
from tests.xlsx_utils import write_xlsx
from tools import evaluate_biopython_pairwise as tool


def write_input(path: Path, *, parent: bool = False) -> None:
    write_xlsx(
        path,
        [
            ["序号", "抗体名称", "VH", "VL", "排序", "类型", "起始VH", "起始VL"],
            [
                1,
                "Candidate",
                "CANDIDATE_H",
                "n/a",
                1,
                "优化改造",
                "PARENT_H" if parent else None,
                None,
            ],
        ],
    )


def write_positive(path: Path, name: str = "Explicit") -> None:
    path.write_text(
        "抗体名称,类型,抗体重链氨基酸,抗体轻链氨基酸\n"
        f"{name},VHH,POSITIVE_H,\n",
        encoding="utf-8",
    )


def parse(*arguments: str):
    return tool.build_parser().parse_args(list(arguments))


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["shadow", "--help"],
        ["validate", "--help"],
    ],
)
def test_tool_help_runs_directly_from_clean_repository(arguments):
    repository = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/evaluate_biopython_pairwise.py",
            *arguments,
        ],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout
    if arguments == ["shadow", "--help"]:
        assert "complete result directory" in completed.stdout
        assert "tool artifacts" in completed.stdout


def test_shadow_parser_exposes_reproducible_defaults():
    args = parse(
        "shadow",
        "--input",
        "benchmark.xlsx",
        "--output-dir",
        "results",
    )

    assert args.command == "shadow"
    assert args.input == Path("benchmark.xlsx")
    assert args.positive_csv is None
    assert args.output_dir == Path("results")
    assert args.workers == 16
    assert args.threshold == 0.8
    assert args.anarci_bin == "ANARCI"
    assert args.muscle_bin == "muscle"
    assert args.max_optimal_alignments == 1000


def test_validate_parser_accepts_each_configuration_source():
    explicit = parse(
        "validate",
        "--input",
        "benchmark.xlsx",
        "--output",
        "failed.csv",
        "--matrix",
        "BLOSUM62",
        "--gap-open",
        "10",
        "--gap-extend",
        "0.5",
    )
    selected = parse(
        "validate",
        "--input",
        "benchmark.xlsx",
        "--output",
        "failed.csv",
        "--config-json",
        "selected.json",
    )

    assert explicit.matrix == "BLOSUM62"
    assert explicit.gap_open == 10.0
    assert explicit.gap_extend == 0.5
    assert selected.config_json == Path("selected.json")


@pytest.mark.parametrize(
    "arguments",
    [
        (),
        ("--matrix", "BLOSUM62", "--gap-open", "10"),
        (
            "--config-json",
            "selected.json",
            "--matrix",
            "BLOSUM62",
            "--gap-open",
            "10",
            "--gap-extend",
            "0.5",
        ),
    ],
)
def test_validate_parser_rejects_missing_or_mixed_configuration(arguments):
    with pytest.raises(SystemExit):
        parse(
            "validate",
            "--input",
            "benchmark.xlsx",
            "--output",
            "failed.csv",
            *arguments,
        )


@pytest.mark.parametrize(
    "command, arguments",
    [
        ("shadow", ("--workers", "0")),
        ("validate", ("--workers", "-1")),
        ("shadow", ("--threshold", "nan")),
        ("validate", ("--threshold", "1.01")),
        ("shadow", ("--max-optimal-alignments", "0")),
    ],
)
def test_parser_rejects_invalid_numeric_ranges(command, arguments):
    common = [
        command,
        "--input",
        "benchmark.xlsx",
        "--output-dir" if command == "shadow" else "--output",
        "output",
    ]
    if command == "validate":
        common.extend(["--config-json", "selected.json"])

    with pytest.raises(SystemExit):
        parse(*common, *arguments)


def test_load_records_uses_explicit_library_and_appends_parent(tmp_path):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    write_input(input_path, parent=True)
    write_positive(positive_path)

    loaded, positives = tool.load_records(input_path, positive_path)

    assert [row.name for row in loaded.candidates] == ["Candidate"]
    assert [row.name for row in positives] == [
        "Explicit",
        "Candidate__parent_reference",
    ]


def test_load_records_uses_builtin_library(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    builtin_path = tmp_path / "builtin.csv"
    write_input(input_path)
    write_positive(builtin_path, name="Builtin")
    monkeypatch.setattr(tool, "get_builtin_positive_csv_path", lambda: builtin_path)

    _loaded, positives = tool.load_records(input_path, None)

    assert [row.name for row in positives] == ["Builtin"]


@dataclass(frozen=True)
class FakeConfig:
    matrix: str
    gap_open: float
    gap_extend: float


class FakeEvaluator:
    instances: list["FakeEvaluator"] = []
    best: FakeConfig | None = FakeConfig("BLOSUM62", 10.0, 0.5)

    def __init__(self, *, configs, threshold, max_optimal_alignments):
        self.configs = configs
        self.threshold = threshold
        self.max_optimal_alignments = max_optimal_alignments
        self.observations = []
        self.__class__.instances.append(self)

    def observe(self, comparison, alignment, identity):
        self.observations.append((comparison, alignment, identity))

    def write(self, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "summary.json").write_text(
            '{"summary":"stable"}\n',
            encoding="utf-8",
        )
        (output_dir / "differences.csv").write_text(
            "candidate_name\n",
            encoding="utf-8",
        )

    def best_passing_config(self):
        return self.best


class FakeNumberer:
    def __init__(self, *, anarci_bin):
        self.anarci_bin = anarci_bin


class FakeMuscleAligner:
    def __init__(self, *, muscle_bin):
        self.muscle_bin = muscle_bin


class RecordingValidator:
    instances: list["RecordingValidator"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    def validate(self, candidates, positives):
        self.candidates = candidates
        self.positives = positives
        comparison = IdentityComparison(
            candidate_name=candidates[0].name,
            candidate_input_type=InputType.NANOBODY,
            cdr_name="CDRH1",
            candidate_cdr="AAAA",
            positive_name=positives[0].name,
            positive_cdr="AAAT",
        )
        observer = self.kwargs.get("comparison_observer")
        if observer is not None:
            observer(comparison, ("AAAA", "AAAT"), 0.75)
        return []


class FakePairwiseAligner:
    def __init__(self, config):
        self.config = config

    def align(self, cdr_name, candidate_cdr, positive_cdr):
        del cdr_name
        return candidate_cdr, positive_cdr


def fake_runtime():
    return SimpleNamespace(
        PairwiseConfig=FakeConfig,
        BiopythonGlobalAligner=FakePairwiseAligner,
        ShadowEvaluator=FakeEvaluator,
        DEFAULT_CONFIGS=(FakeConfig("BLOSUM62", 10.0, 0.5),),
        biopython_version="1.87",
    )


def write_old_output(output_dir: Path) -> dict[str, bytes]:
    output_dir.mkdir()
    for name in (
        "muscle_failed_reasons.csv",
        "summary.json",
        "differences.csv",
        "selected_config.json",
        "environment.json",
    ):
        (output_dir / name).write_bytes(f"old:{name}".encode())
    return {
        path.name: path.read_bytes()
        for path in sorted(output_dir.iterdir())
    }


def read_output(output_dir: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in sorted(output_dir.iterdir())
    }


def test_shadow_constructs_pipeline_and_writes_stable_metadata(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    FakeEvaluator.instances.clear()
    RecordingValidator.instances.clear()
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
        "--workers",
        "7",
        "--threshold",
        "0.75",
        "--max-optimal-alignments",
        "42",
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=RecordingValidator,
    )

    evaluator = FakeEvaluator.instances[-1]
    validator = RecordingValidator.instances[-1]
    assert evaluator.configs == fake_runtime().DEFAULT_CONFIGS
    assert evaluator.threshold == 0.75
    assert evaluator.max_optimal_alignments == 42
    assert validator.kwargs["max_workers"] == 7
    assert isinstance(validator.kwargs["numberer"], FakeNumberer)
    assert isinstance(validator.kwargs["aligner"], FakeMuscleAligner)
    assert evaluator.observations[0][0].candidate_name == "Candidate"
    assert (output_dir / "muscle_failed_reasons.csv").is_file()
    assert json.loads((output_dir / "selected_config.json").read_text()) == {
        "gap_extend": 0.5,
        "gap_open": 10.0,
        "matrix": "BLOSUM62",
    }
    environment = json.loads((output_dir / "environment.json").read_text())
    assert environment["biopython"] == "1.87"
    assert environment["workers"] == 7
    assert environment["threshold"] == 0.75
    assert environment["max_optimal_alignments"] == 42
    assert environment["input_sha256"] == hashlib.sha256(
        input_path.read_bytes()
    ).hexdigest()
    assert environment["positive_csv_sha256"] == hashlib.sha256(
        positive_path.read_bytes()
    ).hexdigest()
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o755


def test_shadow_preserves_existing_output_directory_mode(tmp_path):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    write_old_output(output_dir)
    output_dir.chmod(0o750)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=RecordingValidator,
    )

    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o750


def test_shadow_uses_mode_from_directory_frozen_at_publish_time(tmp_path):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    write_old_output(output_dir)
    output_dir.chmod(0o750)

    class ModeChangingValidator(RecordingValidator):
        def validate(self, candidates, positives):
            failures = super().validate(candidates, positives)
            output_dir.chmod(0o711)
            return failures

    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=ModeChangingValidator,
    )

    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o711


def test_shadow_artifact_files_remain_readable_with_restrictive_umask(
    tmp_path,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    previous_umask = os.umask(0o077)
    try:
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=RecordingValidator,
        )
    finally:
        os.umask(previous_umask)

    assert {
        stat.S_IMODE(path.stat().st_mode)
        for path in output_dir.iterdir()
    } == {0o644}


def test_shadow_removes_stale_selected_config_when_no_configuration_passes(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_old_output(output_dir)
    selected_path = output_dir / "selected_config.json"
    write_input(input_path)
    write_positive(positive_path)
    monkeypatch.setattr(FakeEvaluator, "best", None)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=RecordingValidator,
    )

    assert not selected_path.exists()
    assert set(path.name for path in output_dir.iterdir()) == {
        "differences.csv",
        "environment.json",
        "muscle_failed_reasons.csv",
        "summary.json",
    }


@pytest.mark.parametrize("unknown_kind", ["file", "directory"])
def test_shadow_refuses_to_replace_unknown_output_content_before_validation(
    tmp_path,
    unknown_kind,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_dir)
    unknown_path = output_dir / "keep-me"
    if unknown_kind == "file":
        unknown_path.write_bytes(b"user data")
    else:
        unknown_path.mkdir()
        (unknown_path / "nested").write_bytes(b"user data")
    original_entries = sorted(
        str(path.relative_to(output_dir))
        for path in output_dir.rglob("*")
    )

    class MustNotBeConstructed:
        def __init__(self, **kwargs):
            del kwargs
            raise AssertionError("validation should not start")

    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    with pytest.raises(tool.EvaluationToolError, match="unknown"):
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            validator_factory=MustNotBeConstructed,
        )

    assert {
        name: (output_dir / name).read_bytes()
        for name in old_bytes
    } == old_bytes
    assert sorted(
        str(path.relative_to(output_dir))
        for path in output_dir.rglob("*")
    ) == original_entries


def test_shadow_refuses_unknown_content_added_during_validation(
    tmp_path,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_dir)

    class LateUnknownValidator(RecordingValidator):
        def validate(self, candidates, positives):
            failures = super().validate(candidates, positives)
            (output_dir / "concurrent-user-file").write_bytes(b"keep me")
            return failures

    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    with pytest.raises(tool.EvaluationToolError, match="unknown"):
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=LateUnknownValidator,
        )

    assert {
        name: (output_dir / name).read_bytes()
        for name in old_bytes
    } == old_bytes
    assert (
        output_dir / "concurrent-user-file"
    ).read_bytes() == b"keep me"
    assert not any(
        path.name.startswith(f".{output_dir.name}.staging-")
        for path in tmp_path.iterdir()
    )


def test_shadow_allows_known_artifact_updated_during_validation(
    tmp_path,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    write_old_output(output_dir)

    class LateKnownValidator(RecordingValidator):
        def validate(self, candidates, positives):
            failures = super().validate(candidates, positives)
            (output_dir / "summary.json").write_text(
                "known concurrent update\n",
                encoding="utf-8",
            )
            return failures

    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=LateKnownValidator,
    )

    assert (
        output_dir / "summary.json"
    ).read_text(encoding="utf-8") == '{"summary":"stable"}\n'
    assert set(path.name for path in output_dir.iterdir()) == set(
        tool.SHADOW_ARTIFACT_NAMES
    )


def test_shadow_restores_old_directory_when_frozen_backup_check_fails(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_dir)
    check_count = 0

    def fail_frozen_check(directory):
        nonlocal check_count
        check_count += 1
        if check_count == 2:
            raise OSError("cannot inspect frozen output")
        return []

    monkeypatch.setattr(
        tool,
        "_unknown_output_entries",
        fail_frozen_check,
        raising=False,
    )
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    with pytest.raises(
        tool.EvaluationToolError,
        match="old output was restored",
    ):
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=RecordingValidator,
        )

    assert read_output(output_dir) == old_bytes


def test_shadow_restore_failure_preserves_frozen_backup(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_dir)

    class LateUnknownValidator(RecordingValidator):
        def validate(self, candidates, positives):
            failures = super().validate(candidates, positives)
            (output_dir / "concurrent-user-file").write_bytes(b"keep me")
            return failures

    real_replace = os.replace

    def fail_backup_restore(source, destination):
        if (
            ".backup-" in Path(source).name
            and Path(destination) == output_dir
        ):
            raise OSError("restore blocked")
        real_replace(source, destination)

    monkeypatch.setattr(tool.os, "replace", fail_backup_restore)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    with pytest.raises(
        tool.EvaluationToolError,
        match="restore.*backup",
    ):
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=LateUnknownValidator,
        )

    backups = list(tmp_path.glob(".output.backup-*"))
    assert len(backups) == 1
    assert {
        name: (backups[0] / name).read_bytes()
        for name in old_bytes
    } == old_bytes
    assert (
        backups[0] / "concurrent-user-file"
    ).read_bytes() == b"keep me"


def test_shadow_saves_concurrent_recreated_output_before_restoring_backup(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_dir)
    real_replace = os.replace
    replace_count = 0

    def recreate_after_freeze(source, destination):
        nonlocal replace_count
        replace_count += 1
        real_replace(source, destination)
        if replace_count == 1:
            output_dir.mkdir()
            (output_dir / "concurrent-data").write_bytes(b"do not delete")

    monkeypatch.setattr(tool.os, "replace", recreate_after_freeze)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    with pytest.raises(
        tool.EvaluationToolError,
        match=r"\.concurrent-",
    ) as captured:
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=RecordingValidator,
        )

    assert read_output(output_dir) == old_bytes
    saved_path = next(
        path
        for path in tmp_path.glob(".output.concurrent-*")
        if str(path) in str(captured.value)
    )
    assert (
        saved_path / "concurrent-data"
    ).read_bytes() == b"do not delete"


@pytest.mark.parametrize("failure_phase", ["evaluator", "json"])
def test_shadow_generation_failure_preserves_complete_old_directory(
    tmp_path,
    monkeypatch,
    failure_phase,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_dir)
    runtime = fake_runtime()

    if failure_phase == "evaluator":
        class FailingWriteEvaluator(FakeEvaluator):
            def write(self, output_dir):
                (output_dir / "summary.json").write_text(
                    "partial\n",
                    encoding="utf-8",
                )
                raise RuntimeError("write failed")

        runtime.ShadowEvaluator = FailingWriteEvaluator
    else:
        def fail_json(path, value):
            del path, value
            raise RuntimeError("json failed")

        monkeypatch.setattr(tool, "_write_stable_json", fail_json)

    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    with pytest.raises(RuntimeError):
        tool.run_shadow(
            args,
            runtime=runtime,
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=RecordingValidator,
        )

    assert read_output(output_dir) == old_bytes


def test_shadow_publish_failure_restores_complete_old_directory(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_dir)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )
    real_replace = os.replace
    replace_count = 0

    def fail_new_directory_publish(source, destination):
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("publish failed")
        real_replace(source, destination)

    monkeypatch.setattr(tool.os, "replace", fail_new_directory_publish)

    with pytest.raises(OSError, match="publish failed"):
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=RecordingValidator,
        )

    assert replace_count == 3
    assert read_output(output_dir) == old_bytes
    assert not any(".backup-" in path.name for path in tmp_path.iterdir())


@pytest.mark.parametrize("broken", [False, True])
def test_shadow_rejects_symlink_output_before_validation(
    tmp_path,
    broken,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "output"
    symlink_target = tmp_path / "symlink-target"
    write_input(input_path)
    write_positive(positive_path)
    if not broken:
        write_old_output(symlink_target)
    output_path.symlink_to(symlink_target, target_is_directory=True)

    class MustNotBeConstructed:
        def __init__(self, **kwargs):
            del kwargs
            raise AssertionError("validation should not start")

    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_path),
    )

    with pytest.raises(tool.EvaluationToolError, match="symbolic link"):
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            validator_factory=MustNotBeConstructed,
        )

    assert output_path.is_symlink()
    if not broken:
        assert set(path.name for path in symlink_target.iterdir()) == set(
            tool.SHADOW_ARTIFACT_NAMES
        )


def test_shadow_rejects_output_replaced_by_symlink_after_initial_check(
    tmp_path,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "output"
    displaced_path = tmp_path / "displaced-output"
    symlink_target = tmp_path / "symlink-target"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_path)
    symlink_target.mkdir()

    class SymlinkReplacingValidator(RecordingValidator):
        def validate(self, candidates, positives):
            failures = super().validate(candidates, positives)
            os.replace(output_path, displaced_path)
            output_path.symlink_to(
                symlink_target,
                target_is_directory=True,
            )
            return failures

    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_path),
    )

    with pytest.raises(tool.EvaluationToolError, match="symbolic link"):
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=SymlinkReplacingValidator,
        )

    assert output_path.is_symlink()
    assert output_path.resolve() == symlink_target.resolve()
    assert list(symlink_target.iterdir()) == []
    assert read_output(displaced_path) == old_bytes
    assert not list(tmp_path.glob(".output.backup-*"))


def test_shadow_preserves_concurrent_output_while_restoring_frozen_symlink(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "output"
    displaced_path = tmp_path / "displaced-output"
    symlink_target = tmp_path / "symlink-target"
    write_input(input_path)
    write_positive(positive_path)
    write_old_output(output_path)
    symlink_target.mkdir()

    class SymlinkReplacingValidator(RecordingValidator):
        def validate(self, candidates, positives):
            failures = super().validate(candidates, positives)
            os.replace(output_path, displaced_path)
            output_path.symlink_to(
                symlink_target,
                target_is_directory=True,
            )
            return failures

    real_replace = os.replace
    recreated = False

    def recreate_output_after_freeze(source, destination):
        nonlocal recreated
        real_replace(source, destination)
        if (
            not recreated
            and Path(source) == output_path
            and ".backup-" in Path(destination).name
        ):
            recreated = True
            output_path.mkdir()
            (output_path / "concurrent-data").write_bytes(b"keep me")

    monkeypatch.setattr(
        tool.os,
        "replace",
        recreate_output_after_freeze,
    )
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_path),
    )

    with pytest.raises(
        tool.EvaluationToolError,
        match=r"\.concurrent-",
    ) as captured:
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=SymlinkReplacingValidator,
        )

    assert output_path.is_symlink()
    saved_path = next(
        path
        for path in tmp_path.glob(".output.concurrent-*")
        if str(path) in str(captured.value)
    )
    assert (
        saved_path / "concurrent-data"
    ).read_bytes() == b"keep me"


def test_shadow_reports_and_keeps_backup_when_post_publish_cleanup_fails(
    tmp_path,
    monkeypatch,
    capsys,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_path)
    real_rmtree = tool.shutil.rmtree

    def fail_backup_cleanup(path, *args, **kwargs):
        if ".backup-" in Path(path).name:
            raise OSError("cleanup blocked")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(tool.shutil, "rmtree", fail_backup_cleanup)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_path),
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=RecordingValidator,
        )

    assert (
        output_path / "summary.json"
    ).read_text(encoding="utf-8") == '{"summary":"stable"}\n'
    backups = list(tmp_path.glob(".output.backup-*"))
    assert len(backups) == 1
    stderr = capsys.readouterr().err
    assert str(backups[0]) in stderr
    assert "cleanup blocked" in stderr
    assert read_output(backups[0]) == old_bytes


def test_shadow_ignores_stderr_io_failure_after_successful_publish(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    old_bytes = write_old_output(output_path)
    real_rmtree = tool.shutil.rmtree

    def fail_backup_cleanup(path, *args, **kwargs):
        if ".backup-" in Path(path).name:
            raise OSError("cleanup blocked")
        real_rmtree(path, *args, **kwargs)

    class ClosedStderr:
        def write(self, text):
            del text
            raise OSError("stderr is closed")

    monkeypatch.setattr(tool.shutil, "rmtree", fail_backup_cleanup)
    monkeypatch.setattr(tool.sys, "stderr", ClosedStderr())
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_path),
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=RecordingValidator,
    )

    assert (
        output_path / "summary.json"
    ).read_text(encoding="utf-8") == '{"summary":"stable"}\n'
    backups = list(tmp_path.glob(".output.backup-*"))
    assert len(backups) == 1
    assert read_output(backups[0]) == old_bytes


def test_shadow_does_not_hide_non_io_stderr_programming_error(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    write_old_output(output_path)
    real_rmtree = tool.shutil.rmtree

    def fail_backup_cleanup(path, *args, **kwargs):
        if ".backup-" in Path(path).name:
            raise OSError("cleanup blocked")
        real_rmtree(path, *args, **kwargs)

    class BrokenStderr:
        def write(self, text):
            del text
            raise RuntimeError("stderr implementation bug")

    monkeypatch.setattr(tool.shutil, "rmtree", fail_backup_cleanup)
    monkeypatch.setattr(tool.sys, "stderr", BrokenStderr())
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_path),
    )

    with pytest.raises(RuntimeError, match="implementation bug"):
        tool.run_shadow(
            args,
            runtime=fake_runtime(),
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=RecordingValidator,
        )


def test_shadow_rejects_output_target_that_is_not_a_directory(tmp_path):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    output_path.write_text("not a directory", encoding="utf-8")
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_path),
    )

    with pytest.raises(tool.EvaluationToolError, match="not a directory"):
        tool.run_shadow(args, runtime=fake_runtime())


def test_shadow_loads_and_hashes_the_same_input_snapshots(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    original_input = input_path.read_bytes()
    original_positive = positive_path.read_bytes()
    real_load_input = tool.load_input_file
    real_load_positive = tool.load_positive_library
    RecordingValidator.instances.clear()

    def load_then_mutate_input(snapshot_path):
        loaded = real_load_input(snapshot_path)
        input_path.write_bytes(b"changed after input load")
        return loaded

    def load_then_mutate_positive(snapshot_path):
        positives = real_load_positive(snapshot_path)
        positive_path.write_bytes(b"changed after positive load")
        return positives

    monkeypatch.setattr(tool, "load_input_file", load_then_mutate_input)
    monkeypatch.setattr(
        tool,
        "load_positive_library",
        load_then_mutate_positive,
    )
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=RecordingValidator,
    )

    environment = json.loads(
        (output_dir / "environment.json").read_text(encoding="utf-8")
    )
    assert environment["input_sha256"] == hashlib.sha256(
        original_input
    ).hexdigest()
    assert environment["positive_csv_sha256"] == hashlib.sha256(
        original_positive
    ).hexdigest()
    assert RecordingValidator.instances[-1].candidates[0].name == "Candidate"


def test_shadow_snapshot_failure_has_clear_error(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    write_input(input_path)
    write_positive(positive_path)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(tmp_path / "output"),
    )

    def fail_copy(source, destination):
        del source, destination
        raise OSError("disk unavailable")

    monkeypatch.setattr(tool.shutil, "copyfile", fail_copy)

    with pytest.raises(tool.EvaluationToolError, match="snapshot"):
        tool.run_shadow(args, runtime=fake_runtime())


def test_main_returns_nonzero_when_shadow_snapshot_cannot_be_created(
    tmp_path,
    monkeypatch,
    capsys,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    write_input(input_path)
    write_positive(positive_path)
    monkeypatch.setattr(tool, "load_pairwise_runtime", fake_runtime)

    def fail_copy(source, destination):
        del source, destination
        raise OSError("disk unavailable")

    monkeypatch.setattr(tool.shutil, "copyfile", fail_copy)

    exit_code = tool.main(
        [
            "shadow",
            "--input",
            str(input_path),
            "--positive-csv",
            str(positive_path),
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )

    assert exit_code == 2
    assert "snapshot" in capsys.readouterr().err


def test_shadow_hashes_the_actual_builtin_positive_resource(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    builtin_path = tmp_path / "builtin.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(builtin_path, name="Builtin")
    monkeypatch.setattr(
        tool,
        "get_builtin_positive_csv_path",
        lambda: builtin_path,
    )
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--output-dir",
        str(output_dir),
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=RecordingValidator,
    )

    environment = json.loads(
        (output_dir / "environment.json").read_text(encoding="utf-8")
    )
    assert environment["positive_csv_sha256"] == hashlib.sha256(
        builtin_path.read_bytes()
    ).hexdigest()


def test_shadow_adds_comparison_context_and_preserves_observer_cause(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    write_input(input_path)
    write_positive(positive_path)

    class FailingEvaluator(FakeEvaluator):
        def observe(self, comparison, alignment, identity):
            del comparison, alignment, identity
            raise RuntimeError("alignment explosion")

    runtime = fake_runtime()
    runtime.ShadowEvaluator = FailingEvaluator
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(tmp_path / "output"),
    )

    with pytest.raises(tool.ComparisonExecutionError) as captured:
        tool.run_shadow(
            args,
            runtime=runtime,
            numberer_factory=FakeNumberer,
            muscle_aligner_factory=FakeMuscleAligner,
            validator_factory=RecordingValidator,
        )

    message = str(captured.value)
    assert "candidate=Candidate" in message
    assert "positive=Explicit" in message
    assert "CDR=CDRH1" in message
    assert isinstance(captured.value.__cause__, RuntimeError)


def test_contextual_validator_adds_context_to_aligner_error():
    class FailingAligner:
        def align(self, cdr_name, candidate_cdr, positive_cdr):
            del cdr_name, candidate_cdr, positive_cdr
            raise RuntimeError("MUSCLE crashed")

    validator = tool._ContextualValidator(
        numberer=object(),
        aligner=FailingAligner(),
    )
    comparison = IdentityComparison(
        candidate_name="Candidate",
        candidate_input_type=InputType.NANOBODY,
        cdr_name="CDRH3",
        candidate_cdr="CAR",
        positive_name="Positive",
        positive_cdr="CSR",
    )

    with pytest.raises(tool.ComparisonExecutionError) as captured:
        validator._identity_failure(comparison)

    assert "candidate=Candidate" in str(captured.value)
    assert "positive=Positive" in str(captured.value)
    assert "CDR=CDRH3" in str(captured.value)
    assert isinstance(captured.value.__cause__, RuntimeError)


def test_validate_uses_pairwise_aligner_and_existing_failure_writer(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "failed.csv"
    write_input(input_path)
    write_positive(positive_path)
    RecordingValidator.instances.clear()
    args = parse(
        "validate",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output",
        str(output_path),
        "--matrix",
        "PAM30",
        "--gap-open",
        "9",
        "--gap-extend",
        "1",
    )

    tool.run_validate(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        validator_factory=RecordingValidator,
    )

    aligner = RecordingValidator.instances[-1].kwargs["aligner"]
    assert aligner.config == FakeConfig("PAM30", 9.0, 1.0)
    assert list(csv.DictReader(output_path.open(encoding="utf-8"))) == []


@pytest.mark.parametrize("alias_kind", ["same", "hardlink", "symlink"])
def test_validate_rejects_input_output_collision_before_runtime(
    tmp_path,
    monkeypatch,
    alias_kind,
):
    input_path = tmp_path / "input.xlsx"
    input_path.write_bytes(b"input")
    output_path = (
        input_path if alias_kind == "same" else tmp_path / "failed.csv"
    )
    if alias_kind == "hardlink":
        output_path.hardlink_to(input_path)
    elif alias_kind == "symlink":
        output_path.symlink_to(input_path)
    args = parse(
        "validate",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--matrix",
        "BLOSUM62",
        "--gap-open",
        "11",
        "--gap-extend",
        "1",
    )

    def fail_if_runtime_starts():
        raise AssertionError("runtime must not start")

    monkeypatch.setattr(
        tool,
        "load_pairwise_runtime",
        fail_if_runtime_starts,
    )

    with pytest.raises(ReportPathError, match="must be different"):
        tool.run_validate(args)


def test_validate_main_rejects_collision_before_runtime(
    tmp_path,
    monkeypatch,
    capsys,
):
    input_path = tmp_path / "input.xlsx"
    input_path.write_bytes(b"input")

    def fail_if_runtime_starts():
        raise AssertionError("runtime must not start")

    monkeypatch.setattr(
        tool,
        "load_pairwise_runtime",
        fail_if_runtime_starts,
    )

    exit_code = tool.main(
        [
            "validate",
            "--input",
            str(input_path),
            "--output",
            str(input_path),
            "--matrix",
            "BLOSUM62",
            "--gap-open",
            "11",
            "--gap-extend",
            "1",
        ]
    )

    assert exit_code == 2
    assert "must be different" in capsys.readouterr().err


def test_validate_keeps_open_output_directory_when_parent_is_replaced(
    tmp_path,
):
    input_dir = tmp_path / "input"
    reports = tmp_path / "reports"
    moved_reports = tmp_path / "reports-moved"
    input_dir.mkdir()
    reports.mkdir()
    input_path = input_dir / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = reports / "input.xlsx"
    write_input(input_path)
    original_input = input_path.read_bytes()
    write_positive(positive_path)

    class ParentReplacingValidator(RecordingValidator):
        def validate(self, candidates, positives):
            reports.rename(moved_reports)
            reports.symlink_to(input_dir, target_is_directory=True)
            return super().validate(candidates, positives)

    args = parse(
        "validate",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output",
        str(output_path),
        "--matrix",
        "BLOSUM62",
        "--gap-open",
        "11",
        "--gap-extend",
        "1",
    )

    tool.run_validate(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        validator_factory=ParentReplacingValidator,
    )

    assert input_path.read_bytes() == original_input
    assert (moved_reports / "input.xlsx").is_file()


def test_validate_reads_selected_configuration_json(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_path = tmp_path / "failed.csv"
    config_path = tmp_path / "selected.json"
    write_input(input_path)
    write_positive(positive_path)
    config_path.write_text(
        json.dumps({"matrix": "BLOSUM62", "gap_open": 8, "gap_extend": 1}),
        encoding="utf-8",
    )
    RecordingValidator.instances.clear()
    args = parse(
        "validate",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output",
        str(output_path),
        "--config-json",
        str(config_path),
    )

    tool.run_validate(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        validator_factory=RecordingValidator,
    )

    aligner = RecordingValidator.instances[-1].kwargs["aligner"]
    assert aligner.config == FakeConfig("BLOSUM62", 8.0, 1.0)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "matrix": "BLOSUM62",
            "gap_open": 10,
            "gap_extend": 0.5,
            "extra": "unexpected",
        },
        {"matrix": "BLOSUM62", "gap_open": "10", "gap_extend": 0.5},
        {"matrix": "BLOSUM62", "gap_open": True, "gap_extend": 0.5},
        {"matrix": "BLOSUM62", "gap_open": 10, "gap_extend": False},
        {"matrix": "BLOSUM62", "gap_open": None, "gap_extend": 0.5},
        {"matrix": "   ", "gap_open": 10, "gap_extend": 0.5},
        {"matrix": 62, "gap_open": 10, "gap_extend": 0.5},
        {"matrix": "BLOSUM62", "gap_open": 10},
    ],
)
def test_validate_rejects_non_exact_json_configuration_schema(
    tmp_path,
    payload,
):
    config_path = tmp_path / "selected.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    args = parse(
        "validate",
        "--input",
        "input.xlsx",
        "--output",
        "failed.csv",
        "--config-json",
        str(config_path),
    )

    with pytest.raises(tool.EvaluationToolError):
        tool._load_configuration(args, fake_runtime())


@pytest.mark.parametrize(
    "payload, expected",
    [
        (
            {"matrix": "BLOSUM62", "gap_open": 10, "gap_extend": 0.5},
            FakeConfig("BLOSUM62", 10.0, 0.5),
        ),
        (
            {"matrix": "PAM30", "gap_open": 9.0, "gap_extend": 1},
            FakeConfig("PAM30", 9.0, 1.0),
        ),
        (
            {"matrix": " BLOSUM62 ", "gap_open": 10, "gap_extend": 0.5},
            FakeConfig("BLOSUM62", 10.0, 0.5),
        ),
    ],
)
def test_validate_accepts_json_integer_and_float_gap_values(
    tmp_path,
    payload,
    expected,
):
    config_path = tmp_path / "selected.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    args = parse(
        "validate",
        "--input",
        "input.xlsx",
        "--output",
        "failed.csv",
        "--config-json",
        str(config_path),
    )

    assert tool._load_configuration(args, fake_runtime()) == expected


def test_validate_reports_float_overflow_as_configuration_error(tmp_path):
    config_path = tmp_path / "selected.json"
    config_path.write_text(
        json.dumps(
            {
                "matrix": "BLOSUM62",
                "gap_open": 10**400,
                "gap_extend": 0.5,
            }
        ),
        encoding="utf-8",
    )
    args = parse(
        "validate",
        "--input",
        "input.xlsx",
        "--output",
        "failed.csv",
        "--config-json",
        str(config_path),
    )

    with pytest.raises(tool.EvaluationToolError, match="invalid gap"):
        tool._load_configuration(args, fake_runtime())


def test_shadow_repeated_runs_write_identical_json_bytes(tmp_path, monkeypatch):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    write_input(input_path)
    write_positive(positive_path)
    args = parse(
        "shadow",
        "--input",
        str(input_path),
        "--positive-csv",
        str(positive_path),
        "--output-dir",
        str(output_dir),
    )

    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=RecordingValidator,
    )
    output_names = (
        "selected_config.json",
        "environment.json",
        "summary.json",
        "differences.csv",
        "muscle_failed_reasons.csv",
    )
    first = {
        name: (output_dir / name).read_bytes()
        for name in output_names
    }
    tool.run_shadow(
        args,
        runtime=fake_runtime(),
        numberer_factory=FakeNumberer,
        muscle_aligner_factory=FakeMuscleAligner,
        validator_factory=RecordingValidator,
    )
    second = {
        name: (output_dir / name).read_bytes()
        for name in output_names
    }

    assert first == second


@pytest.mark.parametrize("command", ["shadow", "validate"])
def test_main_reports_optional_dependency_install_hint(
    command,
    tmp_path,
    monkeypatch,
    capsys,
):
    def missing_runtime():
        raise tool.OptionalDependencyError("missing")

    monkeypatch.setattr(tool, "load_pairwise_runtime", missing_runtime)
    input_path = tmp_path / "benchmark.xlsx"
    input_path.write_bytes(b"input")

    arguments = [
        command,
        "--input",
        str(input_path),
        "--output-dir" if command == "shadow" else "--output",
        str(tmp_path / "output"),
    ]
    if command == "validate":
        arguments.extend(
            ["--config-json", str(tmp_path / "selected.json")]
        )

    exit_code = tool.main(arguments)

    assert exit_code != 0
    assert "install ." in capsys.readouterr().err


def test_module_import_and_parser_do_not_require_biopython():
    assert tool.build_parser().prog == "evaluate-biopython-pairwise"


@pytest.mark.parametrize("failure_mode", ["bio_import", "bio_version"])
def test_runtime_reports_biopython_api_failure_with_install_hint(
    monkeypatch,
    failure_mode,
):
    bio = (
        SimpleNamespace()
        if failure_mode == "bio_version"
        else SimpleNamespace(__version__="1.87")
    )

    def import_module(name):
        if name == "Bio":
            if failure_mode == "bio_import":
                raise ImportError(
                    "cannot import Bio.Align",
                    name="Bio.Align",
                )
            return bio
        if name.endswith("biopython_pairwise"):
            return SimpleNamespace(
                PairwiseConfig=FakeConfig,
                BiopythonGlobalAligner=FakePairwiseAligner,
            )
        return SimpleNamespace(
            DEFAULT_CONFIGS=(),
            ShadowEvaluator=FakeEvaluator,
        )

    monkeypatch.setattr(tool.importlib, "import_module", import_module)

    with pytest.raises(tool.OptionalDependencyError) as captured:
        tool.load_pairwise_runtime()

    assert "install ." in str(captured.value)


@pytest.mark.parametrize(
    "internal_error",
    [
        ImportError("project import failed"),
        AttributeError("project attribute failed"),
    ],
)
def test_runtime_does_not_wrap_project_internal_import_errors(
    monkeypatch,
    internal_error,
):
    def import_module(name):
        if name == "Bio":
            return SimpleNamespace(__version__="1.87")
        raise internal_error

    monkeypatch.setattr(tool.importlib, "import_module", import_module)

    with pytest.raises(type(internal_error)) as captured:
        tool.load_pairwise_runtime()

    assert captured.value is internal_error


def test_runtime_does_not_wrap_missing_project_runtime_attributes(
    monkeypatch,
):
    def import_module(name):
        if name == "Bio":
            return SimpleNamespace(__version__="1.87")
        if name.endswith("biopython_pairwise"):
            return SimpleNamespace()
        return SimpleNamespace(
            DEFAULT_CONFIGS=(),
            ShadowEvaluator=FakeEvaluator,
        )

    monkeypatch.setattr(tool.importlib, "import_module", import_module)

    with pytest.raises(AttributeError, match="PairwiseConfig"):
        tool.load_pairwise_runtime()


def test_runtime_does_not_misreport_non_biopython_module_not_found(
    monkeypatch,
):
    def import_module(name):
        if name == "Bio":
            return SimpleNamespace(__version__="1.87")
        raise ModuleNotFoundError(
            "missing unrelated module",
            name="unrelated_dependency",
        )

    monkeypatch.setattr(tool.importlib, "import_module", import_module)

    with pytest.raises(
        ModuleNotFoundError,
        match="missing unrelated module",
    ):
        tool.load_pairwise_runtime()
