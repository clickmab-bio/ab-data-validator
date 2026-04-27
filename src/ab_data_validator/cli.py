from __future__ import annotations

import argparse
import sys
from importlib import resources
from pathlib import Path
from typing import Sequence

from ab_data_validator.anarci_runner import run_anarci
from ab_data_validator.input_loader import InputLoadError, load_input_file
from ab_data_validator.muscle import MuscleError, align_pair
from ab_data_validator.numbering import NumberedResidue
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
    return parser


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
    try:
        loaded_input = load_input_file(args.input)
        with resources.as_file(get_builtin_positive_csv_path()) as positive_path:
            positives = load_positive_library(positive_path) + loaded_input.parent_references
            validator = Validator(
                numberer=numberer or AnarciNumberer(anarci_bin=args.anarci_bin),
                aligner=aligner or MuscleAligner(muscle_bin=args.muscle_bin),
                identity_threshold=args.identity_threshold,
            )
            failures = validator.validate(loaded_input.candidates, positives)
        output_path = args.output or default_output_path(args.input)
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
