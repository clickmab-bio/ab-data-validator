from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class MuscleError(RuntimeError):
    pass


def parse_fasta_alignment(text: str) -> dict[str, str]:
    records: dict[str, list[str]] = {}
    current_name: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            current_name = line[1:].split()[0]
            records[current_name] = []
            continue
        if current_name is None:
            raise MuscleError("alignment FASTA contains sequence data before a header")
        records[current_name].append(line)
    return {name: "".join(parts) for name, parts in records.items()}


def align_pair(
    candidate_cdr: str,
    positive_cdr: str,
    *,
    muscle_bin: str = "muscle",
    runner: CommandRunner | None = None,
) -> tuple[str, str]:
    command_runner = runner or _run_command
    with tempfile.TemporaryDirectory() as directory:
        workdir = Path(directory)
        input_path = workdir / "input.fasta"
        output_path = workdir / "aligned.fasta"
        input_path.write_text(
            f">candidate\n{candidate_cdr}\n>positive\n{positive_cdr}\n",
            encoding="utf-8",
        )
        command = [
            muscle_bin,
            "-align",
            str(input_path),
            "-output",
            str(output_path),
            "-quiet",
        ]
        try:
            completed = command_runner(command)
        except FileNotFoundError as error:
            raise MuscleError(f"MUSCLE executable not found: {muscle_bin}") from error
        if completed.returncode != 0:
            raise MuscleError(f"MUSCLE failed: {completed.stderr}")
        records = parse_fasta_alignment(output_path.read_text(encoding="utf-8"))
    try:
        return records["candidate"], records["positive"]
    except KeyError as error:
        raise MuscleError("MUSCLE output does not contain both aligned records") from error


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)
