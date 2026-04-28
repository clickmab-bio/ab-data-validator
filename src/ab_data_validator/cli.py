from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Sequence

from ab_data_validator.anarci_runner import run_anarci
from ab_data_validator.input_loader import InputLoadError, load_input_file
from ab_data_validator.muscle import MuscleError, align_pair
from ab_data_validator.numbering import NumberedResidue
from ab_data_validator.parallel import resolve_worker_count
from ab_data_validator.positive_library import PositiveLibraryError, load_positive_library
from ab_data_validator.report import write_failure_report
from ab_data_validator.summary import format_validation_summary
from ab_data_validator.validation import Aligner, Numberer, PositiveReferenceError, Validator


class AnarciNumberer:
    def __init__(self, *, anarci_bin: str) -> None:
        self.anarci_bin = anarci_bin

    def number(self, sequence_id: str, sequence: str, chain: str) -> list[NumberedResidue]:
        return run_anarci(
            sequence,
            sequence_id=f"{sequence_id}_{chain}",
            anarci_bin=self.anarci_bin,
        )


class MuscleAligner:
    def __init__(self, *, muscle_bin: str) -> None:
        self.muscle_bin = muscle_bin

    def align(self, cdr_name: str, candidate_cdr: str, positive_cdr: str) -> tuple[str, str]:
        del cdr_name
        return align_pair(candidate_cdr, positive_cdr, muscle_bin=self.muscle_bin)


BEIJING_TZ = timezone(timedelta(hours=8), "UTC+08:00")


def _format_progress_message(message: str, *, now: datetime | None = None) -> str:
    current_time = datetime.now(BEIJING_TZ) if now is None else now
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=BEIJING_TZ)
    current_time = current_time.astimezone(BEIJING_TZ)
    timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
    return f"[{timestamp} UTC+08:00] [ab-data-validator] {message}"


def _print_progress(message: str) -> None:
    print(_format_progress_message(message), file=sys.stderr)


def main(
    argv: Sequence[str] | None = None,
    *,
    numberer: Numberer | None = None,
    aligner: Aligner | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _run_validate(args, numberer=numberer, aligner=aligner)
    parser.print_help(sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ab-data-validator")
    subparsers = parser.add_subparsers(dest="command")
    validate = subparsers.add_parser("validate", help="validate antibody Excel files")
    validate.add_argument("--input", required=True, type=Path, help="candidate antibody Excel file")
    validate.add_argument("--output", type=Path, help="failed-reasons output CSV")
    validate.add_argument("--identity-threshold", default=0.8, type=float)
    validate.add_argument("--anarci-bin", default="ANARCI")
    validate.add_argument("--muscle-bin", default="muscle")
    validate.add_argument(
        "--workers",
        default=0,
        type=_parse_worker_count,
        help="parallel worker count; 0 auto-detects available CPU cores",
    )
    return parser


def _parse_worker_count(value: str) -> int:
    try:
        worker_count = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("workers must be an integer") from error
    if worker_count < 0:
        raise argparse.ArgumentTypeError("workers must be greater than or equal to 0")
    return worker_count


def get_builtin_positive_csv_path():
    return resources.files("ab_data_validator").joinpath("data/positive.csv")


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name("failed_reasons.csv")


def _run_validate(
    args: argparse.Namespace,
    *,
    numberer: Numberer | None,
    aligner: Aligner | None,
) -> int:
    progress_logger = _print_progress
    try:
        progress_logger(f"Loading input: {args.input}")
        loaded_input = load_input_file(args.input)
        progress_logger(
            f"Loaded {len(loaded_input.candidates)} candidates and "
            f"{len(loaded_input.parent_references)} parent references"
        )
        with resources.as_file(get_builtin_positive_csv_path()) as positive_path:
            builtin_positives = load_positive_library(positive_path)
            progress_logger(f"Loaded {len(builtin_positives)} built-in positive references")
            positives = builtin_positives + loaded_input.parent_references
            max_workers = resolve_worker_count(args.workers)
            progress_logger(f"Using {max_workers} worker(s)")
            validator = Validator(
                numberer=numberer or AnarciNumberer(anarci_bin=args.anarci_bin),
                aligner=aligner or MuscleAligner(muscle_bin=args.muscle_bin),
                identity_threshold=args.identity_threshold,
                max_workers=max_workers,
                progress_logger=progress_logger,
            )
            failures = validator.validate(loaded_input.candidates, positives)
        output_path = args.output or default_output_path(args.input)
        progress_logger(f"Writing failure report: {output_path}")
        write_failure_report(output_path, failures)
        print(format_validation_summary(loaded_input.candidates, failures, output_path))
    except (
        InputLoadError,
        MuscleError,
        OSError,
        PositiveLibraryError,
        PositiveReferenceError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
