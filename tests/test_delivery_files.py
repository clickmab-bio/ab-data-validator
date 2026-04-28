from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREBUILT_IMAGE = "clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.2"


def test_dockerfile_defaults_to_official_base_image_and_package_sources():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG BASE_IMAGE=mambaorg/micromamba:1.5.10" in dockerfile
    assert "ARG CONDA_MIRROR=https://repo.anaconda.com" in dockerfile
    assert "ARG CONDA_CUSTOM_CHANNEL_ROOT=https://conda.anaconda.org" in dockerfile
    assert "ARG PIP_INDEX_URL=https://pypi.org/simple" in dockerfile
    assert "custom_channels" in dockerfile
    assert "bioconda: ${CONDA_CUSTOM_CHANNEL_ROOT}" in dockerfile
    assert "repodata_use_zst: false" in dockerfile
    assert "repodata_fns:" in dockerfile
    assert "  - repodata.json" in dockerfile
    assert "pip install --no-build-isolation --no-deps -e ." in dockerfile


def test_readme_documents_excel_only_parent_references_and_summary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "输入文件路径（`.xlsx` 或 `.xlsm`）" in readme
    assert "母本/起始抗体" in readme
    assert "Validation summary" in readme
    assert "examples/demo_submit.xlsx" in readme
    assert "examples/demo_failed_reasons.csv" in readme
    assert "--workers" in readme
    assert PREBUILT_IMAGE in readme
    assert "docker pull clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.2" in readme
    assert "金标准测试数据" in readme
    assert "随意替换、追加或扩展" in readme
    assert "临时追加额外阳性参考" not in readme
    assert "如需扩展阳性参考库" not in readme
    assert "直接修改源码中的 `data/positive.csv`" not in readme
    assert "--input /data/examples/input.csv" not in readme
    assert "性能参考" in readme
    assert "16 核服务器" in readme
    assert "50 条纳米抗体序列" in readme
    assert "耗时大于 37 秒" in readme
    assert "重链 `VH`" in readme
    assert "`>= 128`" in readme
    assert "轻链 `VL`" in readme
    assert "`>= 127`" in readme
    assert "ARD-Y" in readme
    assert "ARDGY" in readme
    assert "identity = 4 / 5 = 0.8" in readme


def test_examples_include_demo_input_and_expected_report():
    demo_input = ROOT / "examples" / "demo_submit.xlsx"
    expected_report = ROOT / "examples" / "demo_failed_reasons.csv"

    assert demo_input.is_file()
    assert demo_input.stat().st_size > 0
    assert expected_report.is_file()
    assert expected_report.read_text(encoding="utf-8").startswith(
        "name,input_type,passed,reason_type,chain,cdr,positive_name,identity,threshold,details"
    )


def test_project_description_mentions_excel_not_csv_user_input():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "Validate antibody Excel files" in pyproject
    assert "Validate antibody CSV files" not in pyproject
