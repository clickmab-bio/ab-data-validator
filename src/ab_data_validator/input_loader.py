from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from ab_data_validator.models import AntibodyRow


BLANK_MARKERS = {"", "n/a", "na", "none", "-", "无"}
CELL_REFERENCE_PATTERN = re.compile(r"^([A-Z]+)(\d+)$")
SPREADSHEET_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class InputLoadError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedInput:
    candidates: list[AntibodyRow]
    parent_references: list[AntibodyRow]


def clean_cell(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in BLANK_MARKERS:
        return None
    return text


def load_input_file(path: str | Path) -> LoadedInput:
    input_path = Path(path)
    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _load_excel_input(input_path)
    raise InputLoadError(f"unsupported input file type: {input_path.suffix}; please provide .xlsx or .xlsm")


def _load_excel_input(path: Path) -> LoadedInput:
    rows = _read_xlsx_rows(path)
    candidates: list[AntibodyRow] = []
    parent_references: list[AntibodyRow] = []

    for row_number, row in enumerate(rows[1:], start=2):
        name = clean_cell(_cell(row, 2))
        vh = _clean_sequence(_cell(row, 3))
        vl = _clean_sequence(_cell(row, 4))
        provided_vh = _clean_sequence(_cell(row, 7))
        provided_vl = _clean_sequence(_cell(row, 8))

        if not any([name, vh, vl, provided_vh, provided_vl]):
            continue
        if name is None:
            raise InputLoadError(f"row {row_number}: name is required")
        if vh is None:
            raise InputLoadError(f"row {row_number}: VH is required")

        candidates.append(AntibodyRow(name=name, vh=vh, vl=vl))
        if provided_vl is not None and provided_vh is None:
            raise InputLoadError(f"row {row_number}: parent reference VH is required when parent reference VL is present")
        if provided_vh is not None:
            parent_references.append(
                AntibodyRow(
                    name=f"{name}__parent_reference",
                    vh=provided_vh,
                    vl=provided_vl,
                )
            )

    return LoadedInput(candidates=candidates, parent_references=parent_references)


def _clean_sequence(value: object | None) -> str | None:
    text = clean_cell(value)
    if text is None:
        return None
    return "".join(text.split())


def _cell(row: list[str | None], one_based_index: int) -> str | None:
    index = one_based_index - 1
    if index >= len(row):
        return None
    return row[index]


def _read_xlsx_rows(path: Path) -> list[list[str | None]]:
    with ZipFile(path) as workbook:
        shared_strings = _read_shared_strings(workbook)
        worksheet_path = _first_worksheet_path(workbook)
        root = ET.fromstring(workbook.read(worksheet_path))

    parsed_rows: list[list[str | None]] = []
    for row in root.findall(".//a:sheetData/a:row", SPREADSHEET_NS):
        parsed_row: list[str | None] = []
        for cell in row.findall("a:c", SPREADSHEET_NS):
            reference = cell.attrib.get("r", "")
            match = CELL_REFERENCE_PATTERN.match(reference)
            if match is None:
                continue
            column_index = _column_index(match.group(1))
            while len(parsed_row) < column_index:
                parsed_row.append(None)
            parsed_row[column_index - 1] = _read_cell_value(cell, shared_strings)
        parsed_rows.append(parsed_row)
    return parsed_rows


def _read_shared_strings(workbook: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    return [
        "".join(text_node.text or "" for text_node in item.findall(".//a:t", SPREADSHEET_NS))
        for item in root.findall("a:si", SPREADSHEET_NS)
    ]


def _first_worksheet_path(workbook: ZipFile) -> str:
    if "xl/worksheets/sheet1.xml" in workbook.namelist():
        return "xl/worksheets/sheet1.xml"
    for name in workbook.namelist():
        if name.startswith("xl/worksheets/") and name.endswith(".xml"):
            return name
    raise InputLoadError("Excel workbook does not contain a worksheet")


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text_node.text or "" for text_node in cell.findall(".//a:t", SPREADSHEET_NS))

    value_node = cell.find("a:v", SPREADSHEET_NS)
    if value_node is None or value_node.text is None:
        return None
    if cell_type == "s":
        return shared_strings[int(value_node.text)]
    return value_node.text


def _column_index(column_name: str) -> int:
    index = 0
    for character in column_name:
        index = index * 26 + (ord(character) - ord("A") + 1)
    return index
