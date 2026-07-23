from __future__ import annotations

import csv
from hashlib import sha256
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from tools.prepare_patent_library import prepare_patent_library


SOURCE_HEADERS = [
    "抗体名称",
    "类型(IgG/VHH)",
    "抗体重链氨基酸",
    "抗体轻链氨基酸(若有)",
    "是否结合PVRIG",
    "是否阻断PVRL2",
    "来自专利",
    "开发公司",
    "相关药物管线",
]


def write_source(path: Path) -> None:
    workbook = Workbook()
    library = workbook.active
    library.title = "参考阳参抗体"
    library.append(SOURCE_HEADERS)
    library.append(["Repeat", "VHH", " acd ef ", None, "是", "是", "P1", "Co", "Drug"])
    library.append(["Repeat", "VHH", "GHIK", None, "否", "是", "P2", "Co", "Drug"])
    library.append(["FirstIgG", "IgG", "LMNP Q", "RST VW", "是", "否", "P3", "Co", "Drug"])
    library.append(["DuplicateIgG", "IgG", "LMNPQ", "RSTVW", "是", "否", "P4", "Co", "Drug"])
    library.append(["备注：仅供核对", None, None, None, None, None, None, None, None])
    library["A6"].fill = PatternFill(fill_type="solid", fgColor="00FF00")
    submission = workbook.create_sheet("抗体提交格式")
    submission.append(
        [
            "序号",
            "抗体名称",
            "重链VH可变区",
            "轻链VL可变区（若为VHH，此处为空）",
            "推荐排序",
            "优化改造/从头设计",
            "起始分子重链序列",
            "起始分子轻链序列（若为VHH，此处为空）",
        ]
    )
    submission.append([1, "existing", "ACDEF", None, 1, "从头设计", None, None])
    workbook.save(path)


def run_preparation(tmp_path: Path, **kwargs):
    source = tmp_path / "source.xlsx"
    write_source(source)
    return prepare_patent_library(
        source_path=source,
        cleaned_path=tmp_path / "cleaned.xlsx",
        csv_path=tmp_path / "positive.csv",
        benchmark_path=tmp_path / "benchmark.xlsx",
        benchmark_size=2,
        **kwargs,
    )


def test_prepare_patent_library_cleans_exports_and_preserves_workbook(tmp_path):
    summary = run_preparation(tmp_path)

    assert summary.source_records == 4
    assert summary.cleaned_records == 3
    assert summary.igg_records == 1
    assert summary.vhh_records == 2
    assert summary.renamed_records == 1
    assert summary.removed_duplicate_records == 1
    assert summary.source_sha256 == sha256((tmp_path / "source.xlsx").read_bytes()).hexdigest()

    cleaned = load_workbook(tmp_path / "cleaned.xlsx")
    assert cleaned.sheetnames == ["参考阳参抗体", "抗体提交格式"]
    rows = list(cleaned.worksheets[0].iter_rows(values_only=True))
    assert [row[0] for row in rows[1:]] == ["Repeat", "Repeat-1", "FirstIgG", "备注：仅供核对"]
    assert rows[1][2] == "ACDEF"
    assert rows[3][2:4] == ("LMNPQ", "RSTVW")
    assert cleaned.worksheets[0]["A5"].fill.fgColor.rgb == "0000FF00"

    with (tmp_path / "positive.csv").open(encoding="utf-8-sig", newline="") as file:
        csv_rows = list(csv.reader(file))
    assert csv_rows[0] == SOURCE_HEADERS
    assert csv_rows[1][0:4] == ["Repeat", "VHH", "ACDEF", ""]
    assert csv_rows[2][0:4] == ["Repeat-1", "VHH", "GHIK", ""]
    assert csv_rows[3][0:4] == ["FirstIgG", "IgG", "LMNPQ", "RSTVW"]
    assert len(csv_rows) == 4

    benchmark = load_workbook(tmp_path / "benchmark.xlsx")
    benchmark_rows = list(benchmark.active.iter_rows(values_only=True))
    assert len(benchmark.worksheets) == 1
    assert [row[1] for row in benchmark_rows[1:]] == ["benchmark_001_Repeat", "benchmark_002_Repeat-1"]
    assert [row[2] for row in benchmark_rows[1:]] == ["ACDEF", "GHIK"]
    assert all(row[3] is None and row[6] is None and row[7] is None for row in benchmark_rows[1:])


def test_prepare_patent_library_rejects_unexpected_source_hash(tmp_path):
    with pytest.raises(ValueError, match="SHA-256"):
        run_preparation(tmp_path, expected_sha256="not-the-source-hash")


def test_prepare_patent_library_requires_requested_vhh_count(tmp_path):
    source = tmp_path / "source.xlsx"
    write_source(source)

    with pytest.raises(ValueError, match="VHH"):
        prepare_patent_library(
            source_path=source,
            cleaned_path=tmp_path / "cleaned.xlsx",
            csv_path=tmp_path / "positive.csv",
            benchmark_path=tmp_path / "benchmark.xlsx",
            benchmark_size=3,
        )


def test_prepare_patent_library_preserves_later_unique_name_during_renaming(tmp_path):
    source = tmp_path / "source.xlsx"
    workbook = Workbook()
    library = workbook.active
    library.title = "参考阳参抗体"
    library.append(SOURCE_HEADERS)
    library.append(["A", "VHH", "ACD", None, None, None, None, None, None])
    library.append(["A", "VHH", "EFG", None, None, None, None, None, None])
    library.append(["A-1", "VHH", "HIK", None, None, None, None, None, None])
    workbook.create_sheet("抗体提交格式")
    workbook.save(source)

    summary = prepare_patent_library(
        source_path=source,
        cleaned_path=tmp_path / "cleaned.xlsx",
        csv_path=tmp_path / "positive.csv",
        benchmark_path=tmp_path / "benchmark.xlsx",
        benchmark_size=3,
    )

    cleaned = load_workbook(tmp_path / "cleaned.xlsx")
    names = [row[0] for row in cleaned.worksheets[0].iter_rows(min_row=2, values_only=True)]
    assert names == ["A", "A-2", "A-1"]
    assert names[2] == "A-1"
    assert len(names) == len(set(names))
    assert summary.renamed_records == 1
