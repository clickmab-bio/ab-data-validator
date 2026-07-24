import csv
from collections import Counter
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
    assert "Excel 工作簿属于本地输入/输出" in readme
    assert "Excel 工作簿仅在本地保存" in readme
    assert "仓库不跟踪 Excel 工作簿" in readme
    assert "examples/demo_submit.xlsx" not in readme
    assert "zhiyaobang_patent_seq_cleaned.xlsx" not in readme
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


def test_quick_start_uses_current_source_for_expanded_library_and_example():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quick_start = readme.split("## 快速开始", 1)[1].split("---", 1)[0]

    assert "docker build -t ab-data-validator ." in quick_start
    assert "当前源码" in quick_start
    assert "307 条阳参" in quick_start
    assert "examples/demo_failed_reasons.csv" in quick_start
    assert PREBUILT_IMAGE not in quick_start
    assert "docker pull" not in quick_start


def test_readme_documents_exact_demo_report_provenance():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "固定 v1.2 运行环境" in readme
    assert "只读挂载当前的 `positive_library.py`、`positive.csv` 和 `report.py`" in readme
    assert "与当前这三项运行逻辑和数据一致" in readme
    assert "由当前源码构建的镜像生成" not in readme


def test_readme_documents_expanded_library_and_openclaw_benchmark():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "307 条阳性参考抗体序列" in readme
    assert "240 条 IgG" in readme
    assert "67 条 VHH" in readme
    assert "净新增 259 条" in readme
    assert "OpenClaw" in readme
    assert "`--workers 16`" in readme
    assert "三次正式运行" in readme
    assert "中位数" in readme
    assert "119.497 秒" in readme
    assert "732.761 秒" in readme
    assert "6.132 倍" in readme


def test_examples_include_expected_report():
    expected_report = ROOT / "examples" / "demo_failed_reasons.csv"
    expected_columns = [
        "name",
        "input_type",
        "passed",
        "reason_type",
        "chain",
        "cdr",
        "positive_name",
        "identity",
        "threshold",
        "details",
    ]

    assert expected_report.is_file()
    with expected_report.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == expected_columns
        rows = list(reader)

    assert len(rows) == 60
    assert all(None not in row.values() for row in rows)
    record_counts = Counter(row["name"] for row in rows)
    assert set(record_counts) == {"HR-151", "HR-151-sim", "Tab5"}
    assert record_counts == Counter(
        {
            "HR-151": 27,
            "HR-151-sim": 27,
            "Tab5": 6,
        }
    )


def test_excel_workbooks_are_ignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "*.[xX][lL][sS]" in gitignore
    assert "*.[xX][lL][sS][xXmMbB]" in gitignore
    assert "*.[xX][lL][tT][xXmM]" in gitignore
    assert "*.[xX][lL][aA][mM]" in gitignore


def test_project_description_mentions_excel_not_csv_user_input():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "Validate antibody Excel files" in pyproject
    assert "Validate antibody CSV files" not in pyproject
