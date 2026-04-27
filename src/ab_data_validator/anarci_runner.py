from __future__ import annotations

import csv
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from ab_data_validator.numbering import NumberedResidue


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
POSITION_PATTERN = re.compile(r"^(?P<position>\d+)(?P<insertion>[A-Za-z]*)$")


class AnarciError(RuntimeError):
    pass


def parse_anarci_csv(text: str) -> list[NumberedResidue]:
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise AnarciError("ANARCI CSV has no header")

    position_columns = [
        column for column in reader.fieldnames if POSITION_PATTERN.match(column or "")
    ]
    residues: list[NumberedResidue] = []
    for row in reader:
        for column in position_columns:
            residue = (row.get(column) or "").strip()
            if not residue or residue in {"-", "."}:
                continue
            match = POSITION_PATTERN.match(column)
            if match is None:
                continue
            residues.append(
                NumberedResidue(
                    position=int(match.group("position")),
                    insertion=match.group("insertion"),
                    residue=residue,
                )
            )
        if residues:
            break

    if not residues:
        raise AnarciError("ANARCI returned no numbered residues")
    return residues


def run_anarci(
    sequence: str,
    *,
    sequence_id: str,
    anarci_bin: str = "ANARCI",
    runner: CommandRunner | None = None,
) -> list[NumberedResidue]:
    command_runner = runner or _run_command
    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        input_path = workdir / "input.fasta"
        output_prefix = workdir / "anarci"
        input_path.write_text(f">{sequence_id}\n{sequence}\n", encoding="utf-8")
        command = [
            anarci_bin,
            "-i",
            str(input_path),
            "-o",
            str(output_prefix),
            "--scheme",
            "imgt",
            "--csv",
        ]
        completed = command_runner(command)
        if completed.returncode != 0:
            raise AnarciError(f"ANARCI failed: {completed.stderr}")
        csv_text = completed.stdout or _read_anarci_output_file(output_prefix)
    return parse_anarci_csv(csv_text)


def _read_anarci_output_file(output_prefix: Path) -> str:
    candidates = [
        output_prefix.with_suffix(".csv"),
        output_prefix.with_suffix(".H.csv"),
        output_prefix.with_suffix(".L.csv"),
        output_prefix.with_suffix(".KL.csv"),
        Path(f"{output_prefix}_H.csv"),
        Path(f"{output_prefix}_L.csv"),
        Path(f"{output_prefix}_KL.csv"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AnarciError("ANARCI did not produce CSV output")


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)
