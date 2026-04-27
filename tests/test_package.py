from ab_data_validator import __version__
from ab_data_validator.cli import get_builtin_positive_csv_path
from ab_data_validator.positive_library import load_positive_library


def test_package_exposes_version():
    assert __version__


def test_builtin_positive_csv_is_packaged():
    positive_path = get_builtin_positive_csv_path()

    assert positive_path.is_file()
    assert positive_path.read_text(encoding="utf-8").startswith("抗体名称,")
    assert len(load_positive_library(positive_path)) > 0
