from importlib import resources

from ab_data_validator.models import InputType
from ab_data_validator.positive_library import load_positive_library


def test_builtin_positive_library_contains_cleaned_patent_sequences():
    positive_csv = resources.files("ab_data_validator").joinpath("data/positive.csv")

    with resources.as_file(positive_csv) as path:
        rows = load_positive_library(path)

    names = {row.name for row in rows}
    pairs = {(row.vh, row.vl) for row in rows}

    assert len(rows) == 307
    assert sum(row.input_type is InputType.FULL_ANTIBODY for row in rows) == 240
    assert sum(row.input_type is InputType.NANOBODY for row in rows) == 67
    assert len(names) == 307
    assert len(pairs) == 307
    assert {"Antibody 1-1", "Antibody 2-1", "Antibody 3-1", "Antibody 4-1", "Clone 15-1"} <= names

    deleted_later_aliases = {
        "Chi-1 (2G10-VH × 2G10-VL)",
        "Chi-72 (3D2-VH × 1D11-VL)",
        "Chi-10 (4E2VH1-VH × 4E2-VL)",
        "Chi-18 (4E2VH2-VH × 4E2-VL)",
        "Chi-27 (4E5-VH × 4E5-VL)",
        "Chi-36 (5B2-VH × 5B2-VL)",
        "Chi-63 (5C10-VH × 5C10-VL)",
        "Chi-45 (6A10-VH × 6A10-VL)",
        "Chi-54 (7C2-VH × 7C2-VL)",
    }
    assert not names & deleted_later_aliases
    assert {
        "2G10 (mouse parent)",
        "3D2 (mouse parent)",
        "4E2VH1 (mouse parent)",
        "4E2VH2 (mouse parent)",
        "4E5 (mouse parent)",
        "5B2 (mouse parent)",
        "5C10 (mouse parent)",
        "6A10 (mouse parent)",
        "7C2 (mouse parent)",
    } <= names
