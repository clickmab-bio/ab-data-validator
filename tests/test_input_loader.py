import pytest

from ab_data_validator.input_loader import InputLoadError, clean_cell, load_input_file
from ab_data_validator.models import InputType
from tests.xlsx_utils import write_xlsx


def test_clean_cell_normalizes_blank_markers():
    for value in ["", " ", "n/a", "N/A", "na", "NA", "none", "None", "-", "无", None]:
        assert clean_cell(value) is None


def test_excel_loader_ignores_header_and_uses_positional_candidate_columns(tmp_path):
    path = tmp_path / "submit.xlsx"
    write_xlsx(
        path,
        [
            ["序号", "抗体名称", "重链VH可变区", "轻链VL可变区", "排序", "类型", "阳参VH", "阳参VL"],
            [1, "CandidateA", " VHAAA ", "n/a", 1, "优化改造", None, None],
            [2, "CandidateB", "VHBBB", " VLBBB ", 2, "从头设计", None, None],
            [3, None, None, None, None, None, None, None],
        ],
    )

    loaded = load_input_file(path)

    assert [row.name for row in loaded.candidates] == ["CandidateA", "CandidateB"]
    assert loaded.candidates[0].vh == "VHAAA"
    assert loaded.candidates[0].vl is None
    assert loaded.candidates[0].input_type is InputType.NANOBODY
    assert loaded.candidates[1].vl == "VLBBB"
    assert loaded.candidates[1].input_type is InputType.FULL_ANTIBODY
    assert loaded.parent_references == []


def test_excel_loader_extracts_column_seven_and_eight_as_parent_references(tmp_path):
    path = tmp_path / "submit.xlsx"
    write_xlsx(
        path,
        [
            ["序号", "抗体名称", "VH", "VL", "排序", "类型", "起始VH", "起始VL"],
            [1, "CandidateA", "VHAAA", "n/a", 1, "优化改造", "POSVHA", None],
            [2, "CandidateB", "VHBBB", "VLBBB", 2, "优化改造", "POSVHB", "POSVLB"],
        ],
    )

    loaded = load_input_file(path)

    assert [row.name for row in loaded.parent_references] == [
        "CandidateA__parent_reference",
        "CandidateB__parent_reference",
    ]
    assert loaded.parent_references[0].vh == "POSVHA"
    assert loaded.parent_references[0].vl is None
    assert loaded.parent_references[1].vh == "POSVHB"
    assert loaded.parent_references[1].vl == "POSVLB"


def test_excel_loader_rejects_parent_light_chain_without_parent_heavy_chain(tmp_path):
    path = tmp_path / "submit.xlsx"
    write_xlsx(
        path,
        [
            ["序号", "抗体名称", "VH", "VL", "排序", "类型", "起始VH", "起始VL"],
            [1, "CandidateA", "VHAAA", "n/a", 1, "优化改造", None, "POSVLA"],
        ],
    )

    with pytest.raises(InputLoadError, match="row 2: parent reference VH is required"):
        load_input_file(path)


def test_user_csv_input_is_not_supported(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("name,VH,VL\nAb1,VHAAA,\n", encoding="utf-8")

    with pytest.raises(InputLoadError, match="unsupported input file type: .csv; please provide .xlsx or .xlsm"):
        load_input_file(path)
