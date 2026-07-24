from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import platform
import shutil
import stat
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterator, Sequence

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
from ab_data_validator.report import (
    prepare_report_destination,
    write_failure_report,
)
from ab_data_validator.validation import (
    IdentityComparison,
    PositiveReferenceError,
    Validator,
)


INSTALL_HINT = "install ."
SHADOW_ARTIFACT_NAMES = frozenset(
    {
        "muscle_failed_reasons.csv",
        "summary.json",
        "differences.csv",
        "selected_config.json",
        "environment.json",
    }
)


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

    shadow = subparsers.add_parser(
        "shadow",
        description=(
            "Write a complete result directory. An existing directory is "
            "replaced and may contain only prior tool artifacts."
        ),
    )
    shadow.add_argument("--input", required=True, type=Path)
    shadow.add_argument("--positive-csv", type=Path)
    shadow.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help=(
            "complete result directory; existing content must contain "
            "only prior tool artifacts"
        ),
    )
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


def _is_bio_import_error(error: ImportError) -> bool:
    return error.name == "Bio" or (
        error.name is not None and error.name.startswith("Bio.")
    )


def load_pairwise_runtime() -> PairwiseRuntime:
    try:
        bio = importlib.import_module("Bio")
    except ModuleNotFoundError as error:
        if _is_bio_import_error(error):
            raise OptionalDependencyError(
                f"Biopython is required; run `pip {INSTALL_HINT}`"
            ) from error
        raise
    except ImportError as error:
        if _is_bio_import_error(error):
            raise OptionalDependencyError(
                f"Biopython is incompatible; run `pip {INSTALL_HINT}`"
            ) from error
        raise

    try:
        pairwise = importlib.import_module(
            "ab_data_validator.biopython_pairwise"
        )
        evaluation = importlib.import_module(
            "ab_data_validator.pairwise_evaluation"
        )
    except ModuleNotFoundError as error:
        if _is_bio_import_error(error):
            raise OptionalDependencyError(
                f"Biopython is required; run `pip {INSTALL_HINT}`"
            ) from error
        raise
    except ImportError as error:
        if _is_bio_import_error(error):
            raise OptionalDependencyError(
                f"Biopython is incompatible; run `pip {INSTALL_HINT}`"
            ) from error
        raise

    try:
        biopython_version = bio.__version__
    except AttributeError as error:
        raise OptionalDependencyError(
            f"Biopython version API is incompatible; "
            f"run `pip {INSTALL_HINT}`"
        ) from error
    return PairwiseRuntime(
        PairwiseConfig=pairwise.PairwiseConfig,
        BiopythonGlobalAligner=pairwise.BiopythonGlobalAligner,
        ShadowEvaluator=evaluation.ShadowEvaluator,
        DEFAULT_CONFIGS=evaluation.DEFAULT_CONFIGS,
        biopython_version=biopython_version,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_snapshot(source: Path, destination: Path, *, label: str) -> None:
    try:
        shutil.copyfile(source, destination)
    except OSError as error:
        raise EvaluationToolError(
            f"cannot create {label} snapshot from {source}: {error}"
        ) from error


@contextmanager
def _input_snapshots(
    input_path: Path,
    positive_csv: Path | None,
) -> Iterator[tuple[Path, Path]]:
    with tempfile.TemporaryDirectory(
        prefix="ab-pairwise-inputs-",
    ) as temporary_directory:
        snapshot_directory = Path(temporary_directory)
        input_snapshot = snapshot_directory / (
            f"input{input_path.suffix}"
        )
        _copy_snapshot(
            input_path,
            input_snapshot,
            label="input",
        )
        with _positive_library_path(positive_csv) as positive_path:
            positive_snapshot = snapshot_directory / (
                f"positive{positive_path.suffix or '.csv'}"
            )
            _copy_snapshot(
                positive_path,
                positive_snapshot,
                label="positive library",
            )
        yield input_snapshot, positive_snapshot


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


def _unknown_output_entries(output_dir: Path) -> list[str]:
    return sorted(
        entry.name
        for entry in output_dir.iterdir()
        if (
            entry.name not in SHADOW_ARTIFACT_NAMES
            or not entry.is_file()
        )
    )


def _validate_output_target(output_dir: Path) -> None:
    if output_dir.is_symlink():
        raise EvaluationToolError(
            f"output target must not be a symbolic link: {output_dir}"
        )
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise EvaluationToolError(
            f"output target is not a directory: {output_dir}"
        )
    unknown_entries = _unknown_output_entries(output_dir)
    if unknown_entries:
        raise EvaluationToolError(
            f"output directory contains unknown or invalid entries: "
            f"{', '.join(unknown_entries)}"
        )


def _path_entry_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _unique_sibling(path: Path, label: str) -> Path:
    return path.with_name(
        f".{path.name}.{label}-{uuid.uuid4().hex}"
    )


def _recover_frozen_output(
    *,
    backup_directory: Path,
    output_directory: Path,
    operation_error: BaseException,
    phase: str,
) -> None:
    concurrent_directory: Path | None = None
    if _path_entry_exists(output_directory):
        concurrent_directory = _unique_sibling(
            output_directory,
            "concurrent",
        )
        try:
            os.replace(output_directory, concurrent_directory)
        except BaseException as preserve_error:
            raise EvaluationToolError(
                f"cannot preserve concurrently recreated output "
                f"{output_directory}; frozen backup remains at "
                f"{backup_directory}: {preserve_error}"
            ) from operation_error
    try:
        os.replace(backup_directory, output_directory)
    except BaseException as restore_error:
        concurrent_note = (
            ""
            if concurrent_directory is None
            else f"; concurrent data was saved at {concurrent_directory}"
        )
        raise EvaluationToolError(
            f"cannot restore frozen backup {backup_directory} to "
            f"{output_directory}{concurrent_note}: {restore_error}"
        ) from operation_error

    if concurrent_directory is not None:
        raise EvaluationToolError(
            f"cannot publish {output_directory}; old output was restored "
            f"and concurrent data was saved at {concurrent_directory}"
        ) from operation_error
    if phase == "inspection":
        if isinstance(operation_error, EvaluationToolError):
            raise operation_error
        raise EvaluationToolError(
            f"cannot inspect frozen output; old output was restored: "
            f"{operation_error}"
        ) from operation_error
    raise operation_error


def _publish_output_directory(
    staging_directory: Path,
    output_directory: Path,
) -> None:
    if not _path_entry_exists(output_directory):
        staging_directory.chmod(0o755)
        os.replace(staging_directory, output_directory)
        return

    backup_directory = _unique_sibling(
        output_directory,
        "backup",
    )
    os.replace(output_directory, backup_directory)
    try:
        frozen_metadata = backup_directory.lstat()
        if stat.S_ISLNK(frozen_metadata.st_mode):
            raise EvaluationToolError(
                f"frozen output must not be a symbolic link: "
                f"{backup_directory}"
            )
        if not stat.S_ISDIR(frozen_metadata.st_mode):
            raise EvaluationToolError(
                f"frozen output is not a directory: {backup_directory}"
            )
        unknown_entries = _unknown_output_entries(backup_directory)
        if unknown_entries:
            raise EvaluationToolError(
                f"frozen output directory contains unknown or invalid "
                f"entries: {', '.join(unknown_entries)}"
            )
        staging_directory.chmod(
            stat.S_IMODE(frozen_metadata.st_mode)
        )
    except BaseException as inspection_error:
        _recover_frozen_output(
            backup_directory=backup_directory,
            output_directory=output_directory,
            operation_error=inspection_error,
            phase="inspection",
        )

    try:
        os.replace(staging_directory, output_directory)
    except BaseException as publish_error:
        _recover_frozen_output(
            backup_directory=backup_directory,
            output_directory=output_directory,
            operation_error=publish_error,
            phase="publish",
        )
    try:
        shutil.rmtree(backup_directory)
    except OSError as cleanup_error:
        try:
            print(
                f"warning: published {output_directory}, but could not "
                f"remove backup {backup_directory}; it was retained: "
                f"{cleanup_error}",
                file=sys.stderr,
            )
        except OSError:
            pass


def _write_shadow_artifacts(
    staging_directory: Path,
    *,
    evaluator,
    failures,
    environment: dict[str, object],
) -> None:
    write_failure_report(
        staging_directory / "muscle_failed_reasons.csv",
        failures,
    )
    evaluator.write(staging_directory)

    best = evaluator.best_passing_config()
    if best is not None:
        _write_stable_json(
            staging_directory / "selected_config.json",
            {
                "matrix": best.matrix,
                "gap_open": best.gap_open,
                "gap_extend": best.gap_extend,
            },
        )
    _write_stable_json(
        staging_directory / "environment.json",
        environment,
    )

    required_outputs = {
        "muscle_failed_reasons.csv",
        "summary.json",
        "differences.csv",
        "environment.json",
    }
    if best is not None:
        required_outputs.add("selected_config.json")
    missing = sorted(
        name
        for name in required_outputs
        if not (staging_directory / name).is_file()
    )
    if missing:
        raise EvaluationToolError(
            f"shadow evaluation did not generate required artifacts: "
            f"{', '.join(missing)}"
        )
    unexpected = sorted(
        entry.name
        for entry in staging_directory.iterdir()
        if (
            entry.name not in SHADOW_ARTIFACT_NAMES
            or not entry.is_file()
        )
    )
    if unexpected:
        raise EvaluationToolError(
            f"shadow evaluation generated unknown artifacts: "
            f"{', '.join(unexpected)}"
        )
    for artifact_name in required_outputs:
        (staging_directory / artifact_name).chmod(0o644)


def run_shadow(
    args: argparse.Namespace,
    *,
    runtime: PairwiseRuntime | SimpleNamespace | None = None,
    numberer_factory: NumbererFactory | None = None,
    muscle_aligner_factory: AlignerFactory | None = None,
    validator_factory: ValidatorFactory | None = None,
) -> None:
    _validate_output_target(args.output_dir)
    selected_runtime = runtime or load_pairwise_runtime()
    make_numberer = numberer_factory or AnarciNumberer
    make_muscle_aligner = muscle_aligner_factory or MuscleAligner
    make_validator = validator_factory or _ContextualValidator
    evaluator = selected_runtime.ShadowEvaluator(
        configs=selected_runtime.DEFAULT_CONFIGS,
        threshold=args.threshold,
        max_optimal_alignments=args.max_optimal_alignments,
    )
    with _input_snapshots(
        args.input,
        args.positive_csv,
    ) as (input_snapshot, positive_snapshot):
        input_sha256 = _sha256(input_snapshot)
        positive_csv_sha256 = _sha256(positive_snapshot)
        loaded = load_input_file(input_snapshot)
        positives = (
            load_positive_library(positive_snapshot)
            + loaded.parent_references
        )
        validator = make_validator(
            numberer=make_numberer(anarci_bin=args.anarci_bin),
            aligner=make_muscle_aligner(muscle_bin=args.muscle_bin),
            identity_threshold=args.threshold,
            max_workers=args.workers,
            comparison_observer=_contextual_observer(evaluator.observe),
        )
        failures = validator.validate(loaded.candidates, positives)

    args.output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{args.output_dir.name}.staging-",
            dir=args.output_dir.parent,
        )
    )
    try:
        environment = {
            "python": platform.python_version(),
            "biopython": selected_runtime.biopython_version,
            "input_sha256": input_sha256,
            "positive_csv_sha256": positive_csv_sha256,
            "workers": args.workers,
            "threshold": args.threshold,
            "max_optimal_alignments": args.max_optimal_alignments,
        }
        _write_shadow_artifacts(
            staging_directory,
            evaluator=evaluator,
            failures=failures,
            environment=environment,
        )
        _publish_output_directory(
            staging_directory,
            args.output_dir,
        )
    finally:
        if staging_directory.exists():
            shutil.rmtree(staging_directory)


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
    required = {"matrix", "gap_open", "gap_extend"}
    actual = set(value)
    if actual != required:
        details = []
        missing = sorted(required - actual)
        unexpected = sorted(actual - required)
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if unexpected:
            details.append(
                f"unexpected keys: {', '.join(unexpected)}"
            )
        raise EvaluationToolError(
            f"configuration {args.config_json} must contain exactly "
            f"matrix, gap_open and gap_extend ({'; '.join(details)})"
        )
    raw_matrix = value["matrix"]
    if not isinstance(raw_matrix, str) or not raw_matrix.strip():
        raise EvaluationToolError(
            f"configuration {args.config_json} has invalid matrix; "
            f"expected a non-empty string"
        )
    gap_values = (value["gap_open"], value["gap_extend"])
    if any(
        isinstance(gap, bool) or not isinstance(gap, (int, float))
        for gap in gap_values
    ):
        raise EvaluationToolError(
            f"configuration {args.config_json} has invalid gap values; "
            f"gap_open and gap_extend must be JSON numbers"
        )
    matrix = raw_matrix.strip()
    try:
        gap_open = float(value["gap_open"])
        gap_extend = float(value["gap_extend"])
    except OverflowError as error:
        raise EvaluationToolError(
            f"configuration {args.config_json} has invalid gap values: "
            f"{error}"
        ) from error
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with prepare_report_destination(
        args.input,
        args.output,
    ) as output_destination:
        selected_runtime = runtime or load_pairwise_runtime()
        config = _load_configuration(args, selected_runtime)
        loaded, positives = load_records(
            args.input,
            args.positive_csv,
        )
        make_numberer = numberer_factory or AnarciNumberer
        make_validator = validator_factory or _ContextualValidator
        validator = make_validator(
            numberer=make_numberer(anarci_bin=args.anarci_bin),
            aligner=selected_runtime.BiopythonGlobalAligner(config),
            identity_threshold=args.threshold,
            max_workers=args.workers,
        )
        failures = validator.validate(
            loaded.candidates,
            positives,
        )
        write_failure_report(output_destination, failures)


def _print_error(error: BaseException) -> None:
    print(f"error: {error}", file=sys.stderr)
    cause = error.__cause__
    if cause is not None:
        print(f"caused by: {cause}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "shadow":
            runtime = load_pairwise_runtime()
            run_shadow(args, runtime=runtime)
        else:
            run_validate(args)
    except (
        EvaluationToolError,
        InputLoadError,
        OSError,
        PositiveLibraryError,
        PositiveReferenceError,
        ValueError,
    ) as error:
        if isinstance(error, OptionalDependencyError):
            message = str(error)
            if INSTALL_HINT not in message:
                message = (
                    f"{message}; run `pip {INSTALL_HINT}`"
                )
            print(
                f"error: {message}",
                file=sys.stderr,
            )
        else:
            _print_error(error)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
