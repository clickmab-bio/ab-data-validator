# Ab Data Validator

🔬 抗体序列数据质量校验工具 — 基于 IMGT 编号体系，自动校验序列完整性并过滤与已知阳性参考高度相似的候选抗体。

![版本](https://img.shields.io/badge/版本-0.1.0-blue)
![许可证](https://img.shields.io/badge/许可证-MIT-green)
![Python](https://img.shields.io/badge/Python-≥3.10-yellow)

---

## 目录

- [快速开始](#快速开始)
- [性能参考](#性能参考)
- [生产比对后端](#生产比对后端)
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

当前生产镜像 v1.3 已包含 307 条阳参库。拉取镜像后即可运行示例校验：

```bash
docker pull clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.3
docker run --rm -v "$PWD:/data" clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.3 \
  validate \
  --input /data/input.xlsx \
  --output /data/examples/failed_reasons.csv
```

运行前请将待分析的 Excel 工作簿放到仓库根目录并命名为 `input.xlsx`，或将
`--input` 改为挂载目录中的实际文件路径。Excel 工作簿属于本地输入/输出，
已由 `.gitignore` 统一忽略，不随仓库分发。

校验结果将输出到 `examples/failed_reasons.csv`。仓库中的
`examples/demo_failed_reasons.csv` 可用于核对失败报告的字段和结构。

---

## 性能参考

当前生产默认参数在 OpenClaw 16 核服务器上的复验使用 50 条 VHH 候选和
307 条内置阳参，结果如下：

| 项目 | 默认测试配置或结果 |
|---|---:|
| 生产镜像 | `v1.3` |
| 比对后端 | Pairwise |
| Pairwise 参数 | Biopython 1.87、BLOSUM62、`gap_open=11`、`gap_extend=1` |
| 默认一致性阈值 | `0.8` |
| 计算资源 | 16 个逻辑 CPU |
| worker | 实测为 `--workers 16`；默认 `--workers 0` 在该环境自动解析为 16 |
| 输入规模 | 50 条 VHH，0 个母本/起始抗体 |
| 内置阳参 | 307 条 |
| CDR 比较量 | 50,490 次 |
| 墙钟时间中位数 | **35.85 秒** |

测试容器固定使用 16 个逻辑 CPU（`0-15`）并禁用网络。除为固定计算资源而显式
指定 16 个 worker 外，比对后端、比对参数和默认一致性阈值 `0.8` 均为生产
默认值；在相同环境中，CLI 默认的 `--workers 0` 也会自动选择 16 个 worker。

该结果用于说明当前默认配置在固定数据规模下的执行效率。实际耗时会受到候选
数量、抗体类型、母本数量、序列长度、CPU 负载和存储性能影响。50 条 VHH
仅用于性能测试，不是带独立真值的准确率数据集，不能用于推断灵敏度、特异度
或误报率。

---

## 生产比对后端

Pairwise 是默认生产比对后端，固定使用 Biopython 1.87、BLOSUM62、
`gap_open=11` 和 `gap_extend=1`。程序不会自动回退到 MUSCLE；Pairwise
执行失败时会报告错误并终止。

需要人工回退时，显式传入 `--aligner muscle`：

```bash
ab-data-validator validate \
  --input input.xlsx \
  --output failed_reasons.csv \
  --aligner muscle
```

MUSCLE 仅是人工选择的兼容后端。使用该后端时才需要安装 MUSCLE，也只有此时
`--muscle-bin` 参数才有效。

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

工具当前内置 **307 条阳性参考抗体序列**，其中 **240 条 IgG**、**67 条 VHH**；相较原有 48 条记录，去重后**净新增 259 条**。CSV 中“来自专利”字段共有 22 个不同来源或来源组合，已独立按逻辑记录核对：

| 来源专利或组合 | 数量 |
|---|---:|
| WO2021180205A1 | 5 |
| WO2023186063A1 | 4 |
| US12312404B2 | 35 |
| US20230227572A1 | 1 |
| US20230227572A2 | 1 |
| US20230227572A3 | 1 |
| US20230227572A4 | 1 |
| CN117957254A | 3 |
| US20250326842A1 | 1 |
| CN120230207A | 7 |
| US11214619B2 / WO2020018879A1 | 13 |
| US20240343803A1 / WO2023006040 | 33 |
| US20240270840A1 / WO2022172267A1 | 8 |
| US20240043530A1 / WO2021180205A1 | 24 |
| WO2017041004A1 | 3 |
| CN119119268A | 11 |
| CN114644711A | 5 |
| CN115819582A | 4 |
| EP4582450A1 / WO2024046245A1 | 3 |
| WO2024251160A1 | 2 |
| WO2024098980A1 | 3 |
| CN114907479B | 139 |

内置阳性参考数据位于 `src/ab_data_validator/data/positive.csv`，共 307 条逻辑记录，随工具包一起分发，是固定的金标准测试数据，**无法通过命令行覆盖**。用于生成内置 CSV 的原始及清洗后 Excel 工作簿仅在本地保存，并由 `.gitignore` 统一忽略，不随仓库分发。

Excel 输入文件第 7/8 列中的母本/起始抗体序列会作为本次运行的额外对照序列，与内置阳参一起参与所有候选抗体的 CDR 一致性过滤。它们不会写回内置阳参库。

> **为什么不允许命令行覆盖内置阳参？**
> 内置阳性参考是用于测试数据一致性过滤的金标准数据集，应保持固定和可追溯。命令行不允许覆盖，也不应从用户输入或常规运行中随意替换、追加或扩展。Excel 第 7/8 列提供的母本/起始抗体只作为本次运行的额外对照参与比较，不会改变内置阳参库。

---

## 推荐使用方式：Docker

当前生产镜像 v1.3 包含当前 307 条阳参库、默认 Pairwise 后端和所需运行依赖：

```bash
docker pull clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.3
```

镜像地址为
`clickmab-hub.tencentcloudcr.com/public/ab-data-validator:v1.3`。如需审计或
修改实现，也可使用仓库内 Dockerfile 自行构建。

Dockerfile 默认使用官方构建源：

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
  --input /data/input.xlsx \
  --output /data/examples/failed_reasons.csv
```

请自行提供本地 Excel 输入文件；仓库不跟踪 Excel 工作簿。
`examples/failed_reasons.csv` 是本地运行产物，已在 `.gitignore` 中忽略。

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

环境配置中固定了 Biopython 和 ANARCI 版本：

```bash
conda install biopython=1.87
conda install bioconda::anarci==2021.02.04
```

仅在人工选择 `--aligner muscle` 时需要 MUSCLE。MUSCLE 封装使用 MUSCLE 5
的命令格式：

```bash
muscle -align input.fasta -output aligned.fasta -quiet
```

---

## 系统要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | ≥ 3.10 | 运行时环境 |
| Biopython | 1.87 | 默认 Pairwise 全局序列比对后端 |
| ANARCI | 2021.02.04 | 抗体编号工具，通过 Conda bioconda 频道安装 |
| MUSCLE | ≥ 5.x | 可选的人工回退比对工具，仅在 `--aligner muscle` 下需要 |
| Docker | 任意版本 | 推荐方式，无需本地安装上述依赖 |

**操作系统兼容性**：

- ✅ Linux — 原生支持（Conda 或 Docker）
- ✅ macOS — 原生支持（Conda 或 Docker）
- ⚠️ Windows — 建议通过 Docker 或 WSL2 使用

> **注意**：通过 pip 安装项目时会安装固定版本的 Biopython；ANARCI 仍需
> 通过 Conda 或 Docker 环境提供。只有人工选择 MUSCLE 后端时才需要另行配置
> MUSCLE。

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
| `--aligner` | 否 | `pairwise` | 序列比对后端，可选 `pairwise` 或 `muscle` |
| `--muscle-bin` | 否 | `muscle` | MUSCLE 可执行文件路径或名称，仅在 `--aligner muscle` 下有效 |
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

默认使用 Pairwise 对每对 CDR 进行全局比对，固定采用 Biopython 1.87、
BLOSUM62、`gap_open=11` 和 `gap_extend=1`。一致性仍按以下公式计算：

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
| 输入和输出路径冲突 | `ReportPathError` | 输入工作簿与失败报告不能指向同一路径或同一文件 |
| ANARCI 执行失败 | 记录为失败行 | 对应行标记为 `anarci_failed`，不中断整体校验 |
| Pairwise 后端失败 | `AlignmentBackendError` | Pairwise 无法产生有效比对时程序终止，不会自动回退 |
| MUSCLE 执行失败 | `MuscleError` | 人工选择 MUSCLE 后，若未安装或比对出错，程序终止 |
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
│   └── demo_failed_reasons.csv # 固定环境生成的参考失败报告
├── src/ab_data_validator/
│   ├── __init__.py         # 包初始化与版本号
│   ├── cli.py              # 命令行入口与参数解析
│   ├── input_loader.py     # Excel 文件加载
│   ├── positive_library.py # 内置阳性参考数据加载
│   ├── models.py           # 数据模型（AntibodyRow、ValidationFailure）
│   ├── anarci_runner.py    # ANARCI 外部调用封装
│   ├── alignment.py        # 生产比对后端选择与配置
│   ├── biopython_pairwise.py # Biopython Pairwise 全局比对封装
│   ├── muscle.py           # MUSCLE 序列比对封装
│   ├── numbering.py        # IMGT 编号完整性校验
│   ├── cdr.py              # CDR 区域提取
│   ├── similarity.py       # 序列一致性计算
│   ├── validation.py       # 核心校验流程编排
│   ├── report.py           # 失败报告 CSV 生成
│   ├── summary.py          # 终端总览输出
│   └── data/
│       └── positive.csv    # 内置 307 条阳性参考序列（240 条 IgG、67 条 VHH）
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
