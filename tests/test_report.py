import csv

from ab_data_validator.models import InputType, ValidationFailure
from ab_data_validator.report import FAILURE_REPORT_COLUMNS, write_failure_report


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_writes_header_when_no_failures(tmp_path):
    path = tmp_path / "failed.csv"

    write_failure_report(path, [])

    assert path.read_text(encoding="utf-8").strip() == ",".join(FAILURE_REPORT_COLUMNS)


def test_writes_failure_rows(tmp_path):
    path = tmp_path / "failed.csv"
    failures = [
        ValidationFailure(
            name="Ab1",
            input_type=InputType.FULL_ANTIBODY,
            reason_type="anarci_failed",
            chain="VH",
            details="VH cannot be numbered by ANARCI",
        ),
        ValidationFailure(
            name="Ab1",
            input_type=InputType.FULL_ANTIBODY,
            reason_type="high_cdr_identity",
            chain="VH",
            cdr="CDRH3",
            positive_name="PositiveA",
            identity=0.9231,
            threshold=0.8,
            details="CDRH3 identity to PositiveA is 0.9231 >= 0.8",
        ),
    ]

    write_failure_report(path, failures)

    rows = read_rows(path)
    assert rows[0]["name"] == "Ab1"
    assert rows[0]["input_type"] == "full_antibody"
    assert rows[0]["passed"] == "false"
    assert rows[0]["reason_type"] == "anarci_failed"
    assert rows[0]["chain"] == "VH"
    assert rows[1]["cdr"] == "CDRH3"
    assert rows[1]["positive_name"] == "PositiveA"
    assert rows[1]["identity"] == "0.9231"
    assert rows[1]["threshold"] == "0.8"
