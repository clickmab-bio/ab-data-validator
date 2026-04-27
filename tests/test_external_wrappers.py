import subprocess

import pytest

from ab_data_validator.anarci_runner import AnarciError, parse_anarci_csv, run_anarci
from ab_data_validator.muscle import MuscleError, align_pair, parse_fasta_alignment


def test_parses_two_aligned_fasta_records():
    records = parse_fasta_alignment(">candidate\nAR-DY\n>positive\nARDYG\n")

    assert records == {"candidate": "AR-DY", "positive": "ARDYG"}


def test_muscle_command_uses_align_and_output_options(tmp_path):
    captured = {}

    def fake_runner(command):
        captured["command"] = command
        output_path = command[command.index("-output") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(">candidate\nARDY-\n>positive\nARDYG\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    aligned = align_pair("ARDY", "ARDYG", muscle_bin="muscle5", runner=fake_runner)

    assert captured["command"][0] == "muscle5"
    assert "-align" in captured["command"]
    assert "-output" in captured["command"]
    assert aligned == ("ARDY-", "ARDYG")


def test_muscle_missing_executable_raises_muscle_error():
    with pytest.raises(MuscleError, match="MUSCLE executable not found"):
        align_pair("ARDY", "ARDY", muscle_bin="definitely-missing-muscle-binary")


def test_parses_anarci_csv_numbering_columns():
    csv_text = (
        "Id,domain_no,chain_type,1,2,27,111A,127\n"
        "Ab1,0,H,E,V,A,G,Y\n"
    )

    residues = parse_anarci_csv(csv_text)

    assert [(item.position, item.insertion, item.residue) for item in residues] == [
        (1, "", "E"),
        (2, "", "V"),
        (27, "", "A"),
        (111, "A", "G"),
        (127, "", "Y"),
    ]


def test_run_anarci_builds_imgt_csv_command():
    captured = {}
    csv_text = "Id,domain_no,chain_type,1,127\nAb1,0,H,E,Y\n"

    def fake_runner(command):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout=csv_text, stderr="")

    residues = run_anarci("EVY", sequence_id="Ab1", anarci_bin="ANARCI", runner=fake_runner)

    assert captured["command"][0] == "ANARCI"
    assert "--scheme" in captured["command"]
    assert "imgt" in captured["command"]
    assert "--csv" in captured["command"]
    assert [residue.position for residue in residues] == [1, 127]


def test_run_anarci_reads_light_chain_kl_csv_output_file():
    csv_text = "Id,domain_no,chain_type,1,127\nAb1,0,K,D,K\n"

    def fake_runner(command):
        output_prefix = command[command.index("-o") + 1]
        with open(f"{output_prefix}_KL.csv", "w", encoding="utf-8") as handle:
            handle.write(csv_text)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    residues = run_anarci("DIQK", sequence_id="Ab1", anarci_bin="ANARCI", runner=fake_runner)

    assert [residue.residue for residue in residues] == ["D", "K"]


def test_anarci_empty_parsed_results_fail():
    with pytest.raises(AnarciError, match="no numbered residues"):
        parse_anarci_csv("Id,domain_no,chain_type,1\n")
