from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from ab_data_validator.models import InputType
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


def test_shadow_removes_stale_selected_config_when_no_configuration_passes(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "input.xlsx"
    positive_path = tmp_path / "positive.csv"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    selected_path = output_dir / "selected_config.json"
    selected_path.write_text('{"stale": true}\n', encoding="utf-8")
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
    monkeypatch,
    capsys,
):
    def missing_runtime():
        raise tool.OptionalDependencyError("missing")

    monkeypatch.setattr(tool, "load_pairwise_runtime", missing_runtime)

    arguments = [
        command,
        "--input",
        "benchmark.xlsx",
        "--output-dir" if command == "shadow" else "--output",
        "output",
    ]
    if command == "validate":
        arguments.extend(["--config-json", "selected.json"])

    exit_code = tool.main(arguments)

    assert exit_code != 0
    assert "install .[pairwise-benchmark]" in capsys.readouterr().err


def test_module_import_and_parser_do_not_require_biopython():
    assert tool.build_parser().prog == "evaluate-biopython-pairwise"
