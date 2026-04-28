# Ab Data Validator

🔬 抗体序列数据质量校验工具 — 基于 IMGT 编号体系，自动校验序列完整性并过滤与已知阳性参考高度相似的候选抗体。

![版本](https://img.shields.io/badge/版本-0.1.0-blue)
![许可证](https://img.shields.io/badge/许可证-MIT-green)
![Python](https://img.shields.io/badge/Python-≥3.10-yellow)

---

## 目录

- [快速开始](#快速开始)
- [性能参考](#性能参考)
- [输入格式](#输入格式)
- [阳性参考数据](#阳性参考数据)
- [推荐使用方式：Docker](#推荐使用方式docker)
- [本地使用方式：Conda](#本地使用方式conda)
- [系统要求](#系统要求)
- [命令行参数](#命令行参数)
- [校验规则](#校验规则)
- [CDR 一致性过滤](#cdr-一致性过滤)
- [失败报告](#失败报告)
- [错误处理](#错误处理)
- [项目结构](#项目结构)
- [开发](#开发)
- [许可证](#许可证)

---

## 快速开始

使用预构建 Docker 镜像运行示例校验：

```bash
docker pull clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.2
docker run --rm -v "$PWD:/data" clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.2 \
  validate \
  --input /data/examples/demo_submit.xlsx
```

校验结果将输出到 `examples/failed_reasons.csv`。仓库同时提供了该示例输入对应的参考结果：`examples/demo_failed_reasons.csv`。

---

## 性能参考

在一台 16 核服务器上执行数据分析时，50 条纳米抗体序列的完整分析耗时大于 37 秒。该数据可作为用户预估运行时间的参考。

实际耗时会受到 ANARCI、MUSCLE、序列长度、阳性参考数量、`--workers` 设置以及服务器当前负载影响。纳米抗体仅比较重链 CDR，但仍需要完成编号、CDR 提取和与参考序列的 CDR 一致性比较。

---

## 输入格式

候选输入只支持 Excel `.xlsx` 或 `.xlsm` 文件。程序会忽略第一行，列名不参与解析。

Excel 按固定列位置读取：

```text
第 2 列 -> 抗体名称
第 3 列 -> 重链 VH 可变区序列
第 4 列 -> 轻链 VL 可变区序列
```

- 抗体名称为必填项。
- `VH` 为必填项。
- `VL` 可以为空。
- 当 `VL` 为空时，该条目被视为纳米抗体（nanobody），仅检查和比较重链 CDR。
- `n/a`、`NA`、`none`、`-`、`无` 等值会被视为空。

Excel 第 7/8 列用于记录改造抗体对应的母本/起始抗体序列：

```text
第 7 列 -> 母本/起始抗体重链序列
第 8 列 -> 母本/起始抗体轻链序列
```

当第 7 列存在序列时，该母本/起始抗体会在本次运行中加入对照序列集合，并与内置阳参一起用于所有候选抗体的 CDR 一致性过滤。第 8 列为空时，该对照序列按纳米抗体处理；第 8 列有序列时，第 7 列也必须有序列。

---

## 阳性参考数据

工具内置了 **48 条阳性参考抗体序列**，涵盖以下来源：

| 来源专利 | 开发公司 | 药物管线 | 类型 | 数量 |
|----------|----------|----------|------|------|
| WO2021180205A1 | 恒瑞 | SHR-2002 | VHH | 5 条 |
| WO2023186063A1 | 普米斯 & BioNTech | PM-1009 | IgG | 4 条 |
| US12312404B2 | Compugen | COM-701 | IgG | 35 条 |
| US20230227572A1–A4 | 天港免疫 | TGI-2 | IgG | 4 条 |

内置阳性参考数据位于 `src/ab_data_validator/data/positive.csv`，共 48 条记录，随工具包一起分发，是固定的金标准测试数据，**无法通过命令行覆盖**。

Excel 输入文件第 7/8 列中的母本/起始抗体序列会作为本次运行的额外对照序列，与内置阳参一起参与所有候选抗体的 CDR 一致性过滤。它们不会写回内置阳参库。

> **为什么不允许命令行覆盖内置阳参？**
> 内置阳性参考是用于测试数据一致性过滤的金标准数据集，应保持固定和可追溯。命令行不允许覆盖，也不应从用户输入或常规运行中随意替换、追加或扩展。Excel 第 7/8 列提供的母本/起始抗体只作为本次运行的额外对照参与比较，不会改变内置阳参库。

---

## 推荐使用方式：Docker

推荐直接使用已构建好的公共镜像：

```bash
docker pull clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.2
```

该镜像仓库 ID 为 `clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.2`，已基于当前 Dockerfile 构建并推送到远端。中国大陆和其他地区用户均可较快拉取，避免本地构建时访问国外基础镜像、Conda 源或 pip 源较慢的问题。

运行校验：

```bash
docker run --rm -v "$PWD:/data" clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.2 \
  validate \
  --input /data/examples/demo_submit.xlsx \
  --output /data/examples/failed_reasons.csv
```

如需审计、修改或自行构建镜像，可使用仓库内 Dockerfile。Dockerfile 默认使用官方构建源：

- 基础镜像默认使用 `mambaorg/micromamba:1.5.10`。
- Conda 默认使用 `https://repo.anaconda.com`，并通过 `https://conda.anaconda.org` 映射 `conda-forge` 与 `bioconda`。
- pip 默认使用 `https://pypi.org/simple`。

构建镜像：

```bash
docker build -t ab-data-validator .
```

如果需要在内网构建，可以覆盖为内网同步的 Micromamba 镜像和包源：

```bash
docker build \
  --build-arg BASE_IMAGE=your-registry.example.com/mambaorg/micromamba:1.5.10 \
  --build-arg CONDA_MIRROR=https://your-conda-mirror.example.com/anaconda \
  --build-arg CONDA_CUSTOM_CHANNEL_ROOT=https://your-conda-mirror.example.com/anaconda/cloud \
  --build-arg PIP_INDEX_URL=https://your-pypi-mirror.example.com/simple \
  -t ab-data-validator .
```

使用本地构建镜像运行校验：

```bash
docker run --rm -v "$PWD:/data" ab-data-validator \
  validate \
  --input /data/examples/demo_submit.xlsx \
  --output /data/examples/failed_reasons.csv
```

仓库内置示例输入为 `examples/demo_submit.xlsx`，对应的参考输出为 `examples/demo_failed_reasons.csv`。`examples/failed_reasons.csv` 是本地运行产物，已在 `.gitignore` 中忽略。

> ⚠️ **安全提示**：当前 Dockerfile 中使用 `USER root` 运行容器，这是为了确保对挂载卷的读写权限。在生产环境中部署时，请注意评估安全风险，或考虑使用 `--user` 参数指定非特权用户运行。

---

## 本地使用方式：Conda

创建环境：

```bash
conda env create -f environment.yml
conda activate ab-data-validator
pip install -e .
```

如果在中国大陆网络环境中安装，建议先配置 Conda 和 pip 镜像源。以清华源为例：

```bash
conda config --set show_channel_urls yes
conda config --add default_channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
conda config --add default_channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
conda config --add default_channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2
conda config --set custom_channels.conda-forge https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
conda config --set custom_channels.bioconda https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
python -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

运行校验：

```bash
ab-data-validator validate \
  --input input.xlsx \
  --output failed_reasons.csv
```

环境配置中固定了 ANARCI 版本：

```bash
conda install bioconda::anarci==2021.02.04
```

MUSCLE 封装使用 MUSCLE 5 的命令格式：

```bash
muscle -align input.fasta -output aligned.fasta -quiet
```

---

## 系统要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | ≥ 3.10 | 运行时环境 |
| ANARCI | 2021.02.04 | 抗体编号工具，通过 Conda bioconda 频道安装 |
| MUSCLE | ≥ 5.x | 序列比对工具，通过 Conda bioconda 频道安装 |
| Docker | 任意版本 | 推荐方式，无需本地安装上述依赖 |

**操作系统兼容性**：

- ✅ Linux — 原生支持（Conda 或 Docker）
- ✅ macOS — 原生支持（Conda 或 Docker）
- ⚠️ Windows — 建议通过 Docker 或 WSL2 使用

> **注意**：`pyproject.toml` 中的 `dependencies` 为空，因为 ANARCI 和 MUSCLE 为外部可执行文件，需通过 Conda 或 Docker 环境安装，不能通过 `pip install` 自动拉取。直接 `pip install` 安装后仍需手动配置 ANARCI 和 MUSCLE 环境。

---

## 命令行参数

```bash
ab-data-validator validate [参数]
```

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` | ✅ 是 | — | 输入文件路径（`.xlsx` 或 `.xlsm`） |
| `--output` | 否 | 输入文件旁的 `failed_reasons.csv` | 失败报告输出路径 |
| `--identity-threshold` | 否 | `0.8` | CDR 一致性阈值，范围 0–1 |
| `--anarci-bin` | 否 | `ANARCI` | ANARCI 可执行文件路径或名称 |
| `--muscle-bin` | 否 | `muscle` | MUSCLE 可执行文件路径或名称 |
| `--workers` | 否 | `0` | 并行 worker 数；`0` 表示按当前可用 CPU 核心数自动检测，`1` 表示串行执行 |

示例 — 使用自定义阈值：

```bash
ab-data-validator validate \
  --input input.xlsx \
  --output failed_reasons.csv \
  --identity-threshold 0.75
```

示例 — 限制并行数量：

```bash
ab-data-validator validate \
  --input input.xlsx \
  --output failed_reasons.csv \
  --workers 4
```

---

## 校验规则

每行数据必须满足以下条件：

- `VH` 能够被 ANARCI 使用 IMGT 方案进行编号。
- 非空的 `VL` 能够被 ANARCI 使用 IMGT 方案进行编号。
- 每条编号后的链包含 IMGT 位置 `1`。
- 重链 `VH` 编号后的最大 IMGT 位置 `>= 128`。
- 轻链 `VL` 编号后的最大 IMGT 位置 `>= 127`。
- 所需的 CDR 区域长度 `>= 1`。

IMGT CDR 区域定义：

```text
CDR1: 27-38
CDR2: 56-65
CDR3: 105-117
```

ANARCI 产生的间隙残基（如 `-`）在提取 CDR 序列时会被忽略。

完整抗体要求具备 `CDRH1/CDRH2/CDRH3/CDRL1/CDRL2/CDRL3`。纳米抗体仅要求 `CDRH1/CDRH2/CDRH3`。

---

## CDR 一致性过滤

每个候选 CDR 仅与阳性参考中对应的 CDR 进行比较，例如 `CDRH1` 与 `CDRH1` 比较。

比较对象包含：

- 内置阳参库中的所有抗体；
- Excel 第 7/8 列提供的所有母本/起始抗体序列。

使用 MUSCLE 对每对 CDR 进行比对。一致性按以下公式计算：

```text
identity = 匹配的比对列数 / 总比对列数
```

间隙列也计入总数。间隙与氨基酸的比对视为不匹配。当任一可比较 CDR 的一致性大于或等于阈值时，该候选即判定为失败。

具体计算示例：

```text
aligned candidate CDR: ARD-Y
aligned positive CDR:  ARDGY
matching columns:       A R D   Y = 4
total aligned columns:  5
identity = 4 / 5 = 0.8
```

在该例中，第 4 列为间隙与氨基酸的比对，不计为匹配，但仍计入总比对列数。因此一致性为 `0.8`。当阈值为默认值 `0.8` 时，因为判定规则是 `identity >= threshold`，该 CDR 会触发高一致性失败。

默认阈值：

```text
0.8
```

---

## 失败报告

输出 CSV 文件中每个失败原因对应一行：

```csv
name,input_type,passed,reason_type,chain,cdr,positive_name,identity,threshold,details
```

### 字段说明

| 字段 | 说明 | 示例值 |
|------|------|--------|
| `name` | 候选抗体名称 | `ExampleCandidate` |
| `input_type` | 输入类型 | `full_antibody`、`nanobody` |
| `passed` | 是否通过 | 始终为 `false`（仅失败记录入表） |
| `reason_type` | 失败原因类型 | `anarci_failed`、`missing_n_terminal`、`c_terminal_too_short`、`empty_cdr`、`high_cdr_identity` |
| `chain` | 涉及的链 | `VH`、`VL` |
| `cdr` | 涉及的 CDR 区域 | `CDRH1`、`CDRL3` 等（仅 CDR 相关失败时有值） |
| `positive_name` | 匹配的阳性参考名称 | `CPA.7.001`（仅一致性失败时有值） |
| `identity` | CDR 一致性数值 | `0.85`（仅一致性失败时有值） |
| `threshold` | 使用的一致性阈值 | `0.8`（仅一致性失败时有值） |
| `details` | 人类可读的详细说明 | `CDRH1 identity to CPA.7.001 is 0.85 >= 0.8` |

### 输出示例

```csv
name,input_type,passed,reason_type,chain,cdr,positive_name,identity,threshold,details
ExampleCandidate,full_antibody,false,high_cdr_identity,VH,CDRH1,ExamplePositive,1,0.8,CDRH1 identity to ExamplePositive is 1 >= 0.8
ExampleCandidate,full_antibody,false,high_cdr_identity,VH,CDRH2,ExamplePositive,1,0.8,CDRH2 identity to ExamplePositive is 1 >= 0.8
ExampleCandidate,full_antibody,false,high_cdr_identity,VL,CDRL1,ExamplePositive,1,0.8,CDRL1 identity to ExamplePositive is 1 >= 0.8
```

如果所有候选均通过校验，输出文件仍会写入，但仅包含表头。

命令执行成功后，终端会输出总览信息：

```text
Validation summary
Total antibodies: 120
Passed: 98
Failed: 22
Failure report: /data/failed_reasons.csv
```

---

## 错误处理

工具在遇到以下情况时会输出错误信息并返回退出码 `2`：

| 错误场景 | 错误类型 | 说明 |
|----------|----------|------|
| 不支持的文件格式 | `InputLoadError` | 仅支持 `.xlsx` 和 `.xlsm` 格式 |
| 抗体名称为空 | `InputLoadError` | Excel 第 2 列不能为空 |
| VH 序列为空 | `InputLoadError` | Excel 第 3 列不能为空 |
| 母本/起始抗体 VL 存在但 VH 缺失 | `InputLoadError` | Excel 第 8 列有值时第 7 列也必须有值 |
| ANARCI 执行失败 | 记录为失败行 | 对应行标记为 `anarci_failed`，不中断整体校验 |
| MUSCLE 执行失败 | `MuscleError` | MUSCLE 未安装或比对出错，程序终止 |
| 阳性参考自身校验失败 | `PositiveReferenceError` | 内置或追加的阳性参考数据无法通过编号校验，程序终止 |
| 文件读写错误 | `OSError` | 输入文件不存在或输出路径无写入权限 |

---

## 项目结构

```text
ab-data-validator/
├── Dockerfile              # Docker 镜像构建文件
├── environment.yml         # Conda 环境配置
├── pyproject.toml          # Python 项目元数据与构建配置
├── LICENSE                 # MIT 许可证
├── README.md               # 本文档
├── examples/
│   ├── demo_submit.xlsx        # 示例输入 Excel
│   └── demo_failed_reasons.csv # 示例输入对应的参考失败报告
├── src/ab_data_validator/
│   ├── __init__.py         # 包初始化与版本号
│   ├── cli.py              # 命令行入口与参数解析
│   ├── input_loader.py     # Excel 文件加载
│   ├── positive_library.py # 内置阳性参考数据加载
│   ├── models.py           # 数据模型（AntibodyRow、ValidationFailure）
│   ├── anarci_runner.py    # ANARCI 外部调用封装
│   ├── muscle.py           # MUSCLE 序列比对封装
│   ├── numbering.py        # IMGT 编号完整性校验
│   ├── cdr.py              # CDR 区域提取
│   ├── similarity.py       # 序列一致性计算
│   ├── validation.py       # 核心校验流程编排
│   ├── report.py           # 失败报告 CSV 生成
│   ├── summary.py          # 终端总览输出
│   └── data/
│       └── positive.csv    # 内置 48 条阳性参考序列
└── tests/                  # 单元测试与集成测试
    ├── test_cli.py
    ├── test_delivery_files.py
    ├── test_external_wrappers.py
    ├── test_input_loader.py
    ├── test_integration_external_tools.py
    ├── test_numbering_and_cdr.py
    ├── test_package.py
    ├── test_report.py
    ├── test_similarity.py
    └── test_validation.py
```

---

## 开发

运行单元测试：

```bash
python -m pytest -v
```

安装 ANARCI 和 MUSCLE 后运行集成测试：

```bash
python -m pytest -m integration -v
```

---

## 许可证

本项目基于 [MIT 许可证](LICENSE) 发布。

Copyright (c) 2026 clickmab-bio
