from __future__ import annotations

from pathlib import Path

from ab_data_validator.models import AntibodyRow, ValidationFailure


def format_validation_summary(
    candidates: list[AntibodyRow],
    failures: list[ValidationFailure],
    failure_report_path: Path,
) -> str:
    failed_names = {failure.name for failure in failures}
    total_count = len(candidates)
    failed_count = len(failed_names)
    passed_count = total_count - failed_count
    return "\n".join(
        [
            "Validation summary",
            f"Total antibodies: {total_count}",
            f"Passed: {passed_count}",
            f"Failed: {failed_count}",
            f"Failure report: {failure_report_path}",
        ]
    )
