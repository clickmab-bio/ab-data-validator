from __future__ import annotations

import csv
from pathlib import Path

from ab_data_validator.input_loader import clean_cell
from ab_data_validator.models import AntibodyRow


class PositiveLibraryError(ValueError):
    pass


def load_positive_library(path: str | Path) -> list[AntibodyRow]:
    rows: list[AntibodyRow] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row_number, row in enumerate(reader, start=2):
            if not any(clean_cell(value) for value in row):
                continue
            name = _required_cell(row, 1, "name", row_number)
            vh = _required_cell(row, 3, "VH", row_number)
            vl = _optional_cell(row, 4)
            rows.append(AntibodyRow(name=name, vh=vh, vl=vl))
    return rows


def _required_cell(row: list[str], one_based_index: int, label: str, row_number: int) -> str:
    value = _optional_cell(row, one_based_index)
    if value is None:
        raise PositiveLibraryError(f"row {row_number}: {label} is required")
    return value


def _optional_cell(row: list[str], one_based_index: int) -> str | None:
    index = one_based_index - 1
    if index >= len(row):
        return None
    value = clean_cell(row[index])
    if value is None:
        return None
    return "".join(value.split())
