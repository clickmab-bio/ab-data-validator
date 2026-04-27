import pytest

from ab_data_validator.positive_library import PositiveLibraryError, load_positive_library


def test_positive_library_uses_column_one_three_and_four(tmp_path):
    path = tmp_path / "positive.csv"
    path.write_text(
        "抗体名称,类型,抗体重链氨基酸,抗体轻链氨基酸,其他\n"
        "PosA,VHH,POSVHA,,x\n"
        "PosB,IgG,POSVHB,POSVLB,x\n",
        encoding="utf-8",
    )

    rows = load_positive_library(path)

    assert [row.name for row in rows] == ["PosA", "PosB"]
    assert rows[0].vh == "POSVHA"
    assert rows[0].vl is None
    assert rows[1].vh == "POSVHB"
    assert rows[1].vl == "POSVLB"


def test_positive_library_rejects_missing_heavy_chain(tmp_path):
    path = tmp_path / "positive.csv"
    path.write_text("抗体名称,类型,抗体重链氨基酸,抗体轻链氨基酸\nPosA,VHH,,\n", encoding="utf-8")

    with pytest.raises(PositiveLibraryError, match="row 2: VH is required"):
        load_positive_library(path)
