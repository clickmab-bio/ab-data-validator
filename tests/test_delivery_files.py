from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_defaults_to_china_friendly_mirrors():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG BASE_IMAGE=m.daocloud.io/docker.io/mambaorg/micromamba:1.5.10" in dockerfile
    assert "ARG CONDA_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/anaconda" in dockerfile
    assert "ARG CONDA_CUSTOM_CHANNEL_ROOT=https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud" in dockerfile
    assert "ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple" in dockerfile
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
    assert "临时追加额外阳性参考" not in readme
    assert "--input /data/examples/input.csv" not in readme


def test_project_description_mentions_excel_not_csv_user_input():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "Validate antibody Excel files" in pyproject
    assert "Validate antibody CSV files" not in pyproject
