"""Prepare the patent antibody library and a VHH benchmark submission workbook."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook


SOURCE_HEADERS = (
    "抗体名称",
    "类型(IgG/VHH)",
    "抗体重链氨基酸",
    "抗体轻链氨基酸(若有)",
    "是否结合PVRIG",
    "是否阻断PVRL2",
    "来自专利",
    "开发公司",
    "相关药物管线",
)
BENCHMARK_HEADERS = (
    "序号",
    "抗体名称",
    "重链VH可变区",
    "轻链VL可变区（若为VHH，此处为空）",
    "推荐排序",
    "优化改造/从头设计",
    "起始分子重链序列",
    "起始分子轻链序列（若为VHH，此处为空）",
)
AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")


@dataclass(frozen=True)
class PreparationSummary:
    source_records: int
    cleaned_records: int
    igg_records: int
    vhh_records: int
    renamed_records: int
    removed_duplicate_records: int
    source_sha256: str


@dataclass
class _Record:
    row: int
    name: str
    kind: str
    vh: str
    vl: str | None
    metadata: list[object | None]


def prepare_patent_library(
    *,
    source_path: Path,
    cleaned_path: Path,
    csv_path: Path,
    benchmark_path: Path,
    benchmark_size: int = 50,
    expected_sha256: str | None = None,
) -> PreparationSummary:
    """Clean a patent source workbook and export its positive and VHH libraries."""
    source_path = Path(source_path)
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if expected_sha256 is not None and source_sha256 != expected_sha256:
        raise ValueError("source SHA-256 does not match expected_sha256")
    if benchmark_size < 0:
        raise ValueError("benchmark_size must not be negative")

    workbook = load_workbook(source_path)
    worksheet = workbook.worksheets[0]
    records = _read_records(worksheet)
    kept, removed_rows = _remove_sequence_duplicates(records)
    renamed_records = _rename_records(kept)
    _ensure_unique(kept)

    for record in kept:
        worksheet.cell(record.row, 1).value = record.name
        worksheet.cell(record.row, 3).value = record.vh
        worksheet.cell(record.row, 4).value = record.vl
    for row in sorted(removed_rows, reverse=True):
        worksheet.delete_rows(row)
    workbook.save(cleaned_path)

    _write_csv(csv_path, kept)
    vhh_records = [record for record in kept if record.kind == "VHH"]
    if len(vhh_records) < benchmark_size:
        raise ValueError(f"requested {benchmark_size} VHH records, found {len(vhh_records)}")
    _write_benchmark(benchmark_path, vhh_records[:benchmark_size])

    return PreparationSummary(
        source_records=len(records),
        cleaned_records=len(kept),
        igg_records=sum(record.kind == "IgG" for record in kept),
        vhh_records=len(vhh_records),
        renamed_records=renamed_records,
        removed_duplicate_records=len(removed_rows),
        source_sha256=source_sha256,
    )


def _read_records(worksheet) -> list[_Record]:
    records = []
    for row in range(2, worksheet.max_row + 1):
        kind = _cell_text(worksheet.cell(row, 2).value)
        vh_value = worksheet.cell(row, 3).value
        if kind not in {"IgG", "VHH"} or not _cell_text(vh_value):
            continue
        name = _cell_text(worksheet.cell(row, 1).value)
        if not name:
            raise ValueError(f"row {row}: antibody name is required")
        vh = _normalise_sequence(vh_value, row, "VH")
        vl_raw = _cell_text(worksheet.cell(row, 4).value)
        if kind == "IgG" and not vl_raw:
            raise ValueError(f"row {row}: IgG requires VL")
        if kind == "VHH" and vl_raw:
            raise ValueError(f"row {row}: VHH must not have VL")
        vl = _normalise_sequence(vl_raw, row, "VL") if vl_raw else None
        records.append(
            _Record(
                row=row,
                name=name,
                kind=kind,
                vh=vh,
                vl=vl,
                metadata=[worksheet.cell(row, column).value for column in range(1, 10)],
            )
        )
    return records


def _cell_text(value: object | None) -> str:
    return str(value).strip() if value is not None else ""


def _normalise_sequence(value: object, row: int, label: str) -> str:
    sequence = re.sub(r"\s+", "", str(value)).upper()
    if not sequence or not set(sequence) <= AMINO_ACIDS:
        raise ValueError(f"row {row}: {label} contains non-standard amino acids")
    return sequence


def _remove_sequence_duplicates(records: list[_Record]) -> tuple[list[_Record], list[int]]:
    seen: set[tuple[str, str | None]] = set()
    kept: list[_Record] = []
    removed_rows: list[int] = []
    for record in records:
        key = (record.vh, record.vl)
        if key in seen:
            removed_rows.append(record.row)
        else:
            seen.add(key)
            kept.append(record)
    return kept, removed_rows


def _rename_records(records: list[_Record]) -> int:
    original_names = {record.name for record in records}
    occurrences: dict[str, int] = {}
    used: set[str] = set()
    renamed = 0
    for record in records:
        original = record.name
        occurrences[original] = occurrences.get(original, 0) + 1
        if occurrences[original] == 1:
            candidate = original
        else:
            suffix = 1
            candidate = f"{original}-{suffix}"
            while candidate in original_names or candidate in used:
                suffix += 1
                candidate = f"{original}-{suffix}"
        record.name = candidate
        used.add(candidate)
        renamed += candidate != original
    return renamed


def _ensure_unique(records: list[_Record]) -> None:
    names = [record.name for record in records]
    sequences = [(record.vh, record.vl) for record in records]
    if len(names) != len(set(names)):
        raise ValueError("cleaned antibody names are not unique")
    if len(sequences) != len(set(sequences)):
        raise ValueError("cleaned VH/VL pairs are not unique")


def _write_csv(path: Path, records: list[_Record]) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(SOURCE_HEADERS)
        for record in records:
            metadata = record.metadata.copy()
            metadata[0] = record.name
            metadata[1] = record.kind
            metadata[2] = record.vh
            metadata[3] = record.vl
            writer.writerow(metadata)


def _write_benchmark(path: Path, records: list[_Record]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "参赛选手提交"
    worksheet.append(BENCHMARK_HEADERS)
    for index, record in enumerate(records, start=1):
        worksheet.append(
            [
                index,
                f"benchmark_{index:03d}_{record.name}",
                record.vh,
                None,
                index,
                "从头设计",
                None,
                None,
            ]
        )
    workbook.save(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--cleaned", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--benchmark-size", type=int, default=50)
    parser.add_argument("--expected-sha256")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = prepare_patent_library(
        source_path=args.source,
        cleaned_path=args.cleaned,
        csv_path=args.csv,
        benchmark_path=args.benchmark,
        benchmark_size=args.benchmark_size,
        expected_sha256=args.expected_sha256,
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
