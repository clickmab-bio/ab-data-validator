from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import platform
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterator, Sequence

from ab_data_validator.cli import (
    AnarciNumberer,
    MuscleAligner,
    get_builtin_positive_csv_path,
)
from ab_data_validator.input_loader import InputLoadError, LoadedInput, load_input_file
from ab_data_validator.models import AntibodyRow
from ab_data_validator.positive_library import (
    PositiveLibraryError,
    load_positive_library,
)
from ab_data_validator.report import write_failure_report
from ab_data_validator.validation import (
    IdentityComparison,
    PositiveReferenceError,
    Validator,
)


INSTALL_HINT = "install .[pairwise-benchmark]"


class EvaluationToolError(RuntimeError):
    pass


class OptionalDependencyError(EvaluationToolError):
    pass


class ComparisonExecutionError(EvaluationToolError):
    pass


class EvaluationArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if parsed.command == "validate":
            _validate_configuration_arguments(self, parsed)
        return parsed


@dataclass(frozen=True)
class PairwiseRuntime:
    PairwiseConfig: type
    BiopythonGlobalAligner: type
    ShadowEvaluator: type
    DEFAULT_CONFIGS: tuple
    biopython_version: str


ValidatorFactory = Callable[..., Validator]
NumbererFactory = Callable[..., object]
AlignerFactory = Callable[..., object]


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _finite_threshold(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("threshold must be a number") from error
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError(
            "threshold must be finite and between 0 and 1"
        )
    return parsed


def _positive_finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(
            "must be finite and greater than 0"
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = EvaluationArgumentParser(prog="evaluate-biopython-pairwise")
    subparsers = parser.add_subparsers(dest="command", required=True)

    shadow = subparsers.add_parser("shadow")
    shadow.add_argument("--input", required=True, type=Path)
    shadow.add_argument("--positive-csv", type=Path)
    shadow.add_argument("--output-dir", required=True, type=Path)
    shadow.add_argument("--workers", default=16, type=_positive_integer)
    shadow.add_argument("--threshold", default=0.8, type=_finite_threshold)
    shadow.add_argument("--anarci-bin", default="ANARCI")
    shadow.add_argument("--muscle-bin", default="muscle")
    shadow.add_argument(
        "--max-optimal-alignments",
        default=1000,
        type=_positive_integer,
    )

    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", required=True, type=Path)
    validate.add_argument("--positive-csv", type=Path)
    validate.add_argument("--output", required=True, type=Path)
    validate.add_argument("--workers", default=16, type=_positive_integer)
    validate.add_argument("--threshold", default=0.8, type=_finite_threshold)
    validate.add_argument("--anarci-bin", default="ANARCI")
    validate.add_argument("--config-json", type=Path)
    validate.add_argument("--matrix")
    validate.add_argument("--gap-open", type=_positive_finite_float)
    validate.add_argument("--gap-extend", type=_positive_finite_float)
    return parser


def _validate_configuration_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    explicit_values = (args.matrix, args.gap_open, args.gap_extend)
    has_any_explicit = any(value is not None for value in explicit_values)
    has_all_explicit = all(value is not None for value in explicit_values)
    if args.config_json is not None and has_any_explicit:
        parser.error(
            "--config-json cannot be combined with "
            "--matrix/--gap-open/--gap-extend"
        )
    if args.config_json is None and not has_all_explicit:
        parser.error(
            "provide --config-json or all of "
            "--matrix, --gap-open and --gap-extend"
        )


@contextmanager
def _positive_library_path(
    positive_csv: Path | None,
) -> Iterator[Path]:
    if positive_csv is not None:
        yield positive_csv
        return
    with resources.as_file(get_builtin_positive_csv_path()) as packaged_path:
        yield packaged_path


def load_records(
    input_path: Path,
    positive_csv: Path | None,
) -> tuple[LoadedInput, list[AntibodyRow]]:
    loaded = load_input_file(input_path)
    with _positive_library_path(positive_csv) as positive_path:
        positives = load_positive_library(positive_path)
    return loaded, positives + loaded.parent_references


def load_pairwise_runtime() -> PairwiseRuntime:
    try:
        bio = importlib.import_module("Bio")
        pairwise = importlib.import_module(
            "ab_data_validator.biopython_pairwise"
        )
        evaluation = importlib.import_module(
            "ab_data_validator.pairwise_evaluation"
        )
    except ModuleNotFoundError as error:
        if error.name == "Bio" or (
            error.name is not None and error.name.startswith("Bio.")
        ):
            raise OptionalDependencyError(
                f"Biopython is required; run `pip {INSTALL_HINT}`"
            ) from error
        raise
    return PairwiseRuntime(
        PairwiseConfig=pairwise.PairwiseConfig,
        BiopythonGlobalAligner=pairwise.BiopythonGlobalAligner,
        ShadowEvaluator=evaluation.ShadowEvaluator,
        DEFAULT_CONFIGS=evaluation.DEFAULT_CONFIGS,
        biopython_version=bio.__version__,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_stable_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _comparison_context(comparison: IdentityComparison) -> str:
    return (
        f"candidate={comparison.candidate_name}, "
        f"positive={comparison.positive_name}, "
        f"CDR={comparison.cdr_name}"
    )


def _contextual_observer(observer):
    def observe(comparison, alignment, identity):
        try:
            observer(comparison, alignment, identity)
        except Exception as error:
            raise ComparisonExecutionError(
                f"pairwise observer failed for "
                f"{_comparison_context(comparison)}: {error}"
            ) from error

    return observe


class _ContextualValidator(Validator):
    def _identity_failure(self, comparison):
        try:
            return super()._identity_failure(comparison)
        except ComparisonExecutionError:
            raise
        except Exception as error:
            raise ComparisonExecutionError(
                f"comparison failed for "
                f"{_comparison_context(comparison)}: {error}"
            ) from error


def run_shadow(
    args: argparse.Namespace,
    *,
    runtime: PairwiseRuntime | SimpleNamespace | None = None,
    numberer_factory: NumbererFactory | None = None,
    muscle_aligner_factory: AlignerFactory | None = None,
    validator_factory: ValidatorFactory | None = None,
) -> None:
    selected_runtime = runtime or load_pairwise_runtime()
    make_numberer = numberer_factory or AnarciNumberer
    make_muscle_aligner = muscle_aligner_factory or MuscleAligner
    make_validator = validator_factory or _ContextualValidator
    evaluator = selected_runtime.ShadowEvaluator(
        configs=selected_runtime.DEFAULT_CONFIGS,
        threshold=args.threshold,
        max_optimal_alignments=args.max_optimal_alignments,
    )
    loaded = load_input_file(args.input)

    with _positive_library_path(args.positive_csv) as positive_path:
        positives = (
            load_positive_library(positive_path)
            + loaded.parent_references
        )
        positive_csv_sha256 = _sha256(positive_path)
        validator = make_validator(
            numberer=make_numberer(anarci_bin=args.anarci_bin),
            aligner=make_muscle_aligner(muscle_bin=args.muscle_bin),
            identity_threshold=args.threshold,
            max_workers=args.workers,
            comparison_observer=_contextual_observer(evaluator.observe),
        )
        failures = validator.validate(loaded.candidates, positives)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_failure_report(
        args.output_dir / "muscle_failed_reasons.csv",
        failures,
    )
    evaluator.write(args.output_dir)

    selected_path = args.output_dir / "selected_config.json"
    best = evaluator.best_passing_config()
    if best is None:
        selected_path.unlink(missing_ok=True)
    else:
        _write_stable_json(
            selected_path,
            {
                "matrix": best.matrix,
                "gap_open": best.gap_open,
                "gap_extend": best.gap_extend,
            },
        )

    _write_stable_json(
        args.output_dir / "environment.json",
        {
            "python": platform.python_version(),
            "biopython": selected_runtime.biopython_version,
            "input_sha256": _sha256(args.input),
            "positive_csv_sha256": positive_csv_sha256,
            "workers": args.workers,
            "threshold": args.threshold,
            "max_optimal_alignments": args.max_optimal_alignments,
        },
    )


def _load_configuration(
    args: argparse.Namespace,
    runtime: PairwiseRuntime | SimpleNamespace,
):
    if args.config_json is None:
        return runtime.PairwiseConfig(
            matrix=args.matrix,
            gap_open=args.gap_open,
            gap_extend=args.gap_extend,
        )
    try:
        value = json.loads(args.config_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationToolError(
            f"cannot read configuration {args.config_json}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise EvaluationToolError(
            f"configuration {args.config_json} must contain a JSON object"
        )
    required = ("matrix", "gap_open", "gap_extend")
    missing = [name for name in required if name not in value]
    if missing:
        raise EvaluationToolError(
            f"configuration {args.config_json} is missing: "
            f"{', '.join(missing)}"
        )
    try:
        matrix = value["matrix"]
        gap_open = float(value["gap_open"])
        gap_extend = float(value["gap_extend"])
    except (TypeError, ValueError) as error:
        raise EvaluationToolError(
            f"configuration {args.config_json} has invalid gap values"
        ) from error
    if not isinstance(matrix, str) or not matrix:
        raise EvaluationToolError(
            f"configuration {args.config_json} has invalid matrix"
        )
    try:
        return runtime.PairwiseConfig(
            matrix=matrix,
            gap_open=gap_open,
            gap_extend=gap_extend,
        )
    except ValueError as error:
        raise EvaluationToolError(
            f"configuration {args.config_json} is invalid: {error}"
        ) from error


def run_validate(
    args: argparse.Namespace,
    *,
    runtime: PairwiseRuntime | SimpleNamespace | None = None,
    numberer_factory: NumbererFactory | None = None,
    validator_factory: ValidatorFactory | None = None,
) -> None:
    selected_runtime = runtime or load_pairwise_runtime()
    config = _load_configuration(args, selected_runtime)
    loaded, positives = load_records(args.input, args.positive_csv)
    make_numberer = numberer_factory or AnarciNumberer
    make_validator = validator_factory or _ContextualValidator
    validator = make_validator(
        numberer=make_numberer(anarci_bin=args.anarci_bin),
        aligner=selected_runtime.BiopythonGlobalAligner(config),
        identity_threshold=args.threshold,
        max_workers=args.workers,
    )
    failures = validator.validate(loaded.candidates, positives)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_failure_report(args.output, failures)


def _print_error(error: BaseException) -> None:
    print(f"error: {error}", file=sys.stderr)
    cause = error.__cause__
    if cause is not None:
        print(f"caused by: {cause}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        runtime = load_pairwise_runtime()
        if args.command == "shadow":
            run_shadow(args, runtime=runtime)
        else:
            run_validate(args, runtime=runtime)
    except (
        EvaluationToolError,
        InputLoadError,
        OSError,
        PositiveLibraryError,
        PositiveReferenceError,
        ValueError,
    ) as error:
        if isinstance(error, OptionalDependencyError):
            print(
                f"error: Biopython is required; "
                f"run `pip {INSTALL_HINT}`",
                file=sys.stderr,
            )
        else:
            _print_error(error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
