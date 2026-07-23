# Patent Sequence Library Expansion Design

Date: 2026-07-23

## Objective

Expand the built-in patent-positive antibody reference library from the current
48 records using the first worksheet of `zhiyaobang_patent_seq.xlsx`, validate
the expanded data, measure its end-to-end performance impact on a 16-core
OpenClaw server, and integrate the accepted result into the repository without
developing directly on `main`.

The benchmark must measure the current implementation before any performance
optimization so that the effect of reference-library growth remains observable.

## Verified Source State

The source workbook has two worksheets:

1. `参考阳参抗体`, containing the patent-positive reference data.
2. `抗体提交格式`, containing the candidate submission example/template.

The inspected source workbook SHA-256 is
`d1fded442244b66b834f7d9006934a5f810d67ddb1342663ed9ef60c55581656`.

The first worksheet contains 316 valid antibody records: 249 IgG and 67 VHH.
All 316 antibodies, covering 565 VH/VL chains, passed the current project rules:

- ANARCI numbering with the IMGT scheme;
- IMGT position 1 present;
- heavy-chain terminal position at least 128;
- light-chain terminal position at least 127;
- all required CDRs non-empty;
- amino-acid characters limited to the standard 20-letter alphabet; and
- IgG/VHH type consistent with light-chain presence.

The validation used 16 local workers and took 194.811 seconds. This is a data
quality check, not the official OpenClaw performance benchmark.

Passing these checks means that the sequences can be processed as antibody
variable regions by this project. It does not independently verify patent
transcription, antigen binding, biological function, species, or the scientific
correctness of every VH/VL pairing.

## Data Cleaning Rules

The source workbook remains unchanged. A cleaned copy named
`zhiyaobang_patent_seq_cleaned.xlsx` will be created while retaining both
worksheets, their ordering, formatting, and the note on the first worksheet.

### Duplicate names

Keep the first occurrence unchanged and append `-1` to the second occurrence:

| Original row | Original name | Cleaned name |
|---:|---|---|
| 158 | `Antibody 1` | `Antibody 1-1` |
| 159 | `Antibody 2` | `Antibody 2-1` |
| 160 | `Antibody 3` | `Antibody 3-1` |
| 161 | `Antibody 4` | `Antibody 4-1` |
| 108 | `Clone 15` | `Clone 15-1` |

These proposed names do not collide with any existing name.

### Exact sequence duplicates

An exact duplicate means that normalized VH and VL are both identical after
removing whitespace. Keep the first occurrence and remove the later occurrence.

| Keep row | Kept antibody | Remove row | Removed antibody |
|---:|---|---:|---|
| 171 | `2G10 (mouse parent)` | 186 | `Chi-1 (2G10-VH × 2G10-VL)` |
| 172 | `3D2 (mouse parent)` | 257 | `Chi-72 (3D2-VH × 1D11-VL)` |
| 173 | `4E2VH1 (mouse parent)` | 196 | `Chi-10 (4E2VH1-VH × 4E2-VL)` |
| 174 | `4E2VH2 (mouse parent)` | 197 | `Chi-18 (4E2VH2-VH × 4E2-VL)` |
| 175 | `4E5 (mouse parent)` | 207 | `Chi-27 (4E5-VH × 4E5-VL)` |
| 177 | `5B2 (mouse parent)` | 217 | `Chi-36 (5B2-VH × 5B2-VL)` |
| 178 | `5C10 (mouse parent)` | 247 | `Chi-63 (5C10-VH × 5C10-VL)` |
| 180 | `6A10 (mouse parent)` | 227 | `Chi-45 (6A10-VH × 6A10-VL)` |
| 183 | `7C2 (mouse parent)` | 237 | `Chi-54 (7C2-VH × 7C2-VL)` |

Rows are identified against the unmodified source workbook. When editing the
workbook, removals must be applied from the greatest row number to the least so
that earlier row references remain stable.

Duplicate VH-only groups are retained because different light-chain pairings
represent distinct antibody records.

### Notes and metadata

The note at original row 319 is retained in the cleaned workbook but excluded
from the program data. Patent, company, pipeline, and other source metadata are
preserved as supplied; this work does not make unrequested scientific or
editorial corrections to them.

The cleaned result must contain exactly 307 antibodies:

- 240 IgG;
- 67 VHH;
- 307 unique names; and
- 307 unique normalized `(VH, VL)` pairs.

Compared with the current 48-record library, this is a net addition of 259
records.

## Program Data Export

The cleaned first worksheet will be exported to
`src/ab_data_validator/data/positive.csv` using the existing nine-column schema.
Only rows with type `IgG` or `VHH` and a non-empty VH are exported. Sequence
whitespace is removed. The cleaned workbook remains the reviewable source
artifact, while `positive.csv` remains the package runtime artifact.

The loader interface and command-line interface remain unchanged. This is a
controlled update of the versioned built-in gold reference library, not a new
runtime override mechanism.

## Benchmark Design

### Workload

Select the first 50 distinct VHH records in cleaned worksheet order. Create a
fixed candidate workbook using the project's existing candidate Excel layout.
This workload is exclusively for performance comparison; because the candidates
originate from known-positive data, its pass/fail rate is not an accuracy
metric.

The same candidate workbook and application code are used in both variants:

- **Baseline:** current 48-record built-in library.
- **Expanded:** cleaned 307-record library.

The expected MUSCLE comparison counts are:

- baseline: `50 × 48 × 3 = 7,200`;
- expanded: `50 × 307 × 3 = 46,050`;
- theoretical comparison-count multiplier: approximately `6.40×`.

### Environment

Run on host `openclaw`, which has 16 online CPU cores and Docker. ANARCI and
MUSCLE are not installed directly on the host, so both variants run in the same
project Docker environment. Capture:

- hostname and kernel;
- CPU model and online CPU count;
- total memory;
- Docker version;
- Docker image identifier/digest; and
- Git commit under test.

Both variants use `--workers 16`. No other CPU-intensive benchmark jobs should
run concurrently.

### Repetitions and ordering

Run one untimed warm-up for each variant, followed by three measured executions
per variant. Alternate baseline and expanded executions to reduce ordering and
machine-load bias. Preserve every raw timing log.

### Metrics

For each run, record:

- wall-clock duration;
- CPU utilization;
- maximum resident memory;
- positive-reference numbering duration;
- candidate numbering duration;
- CDR comparison duration;
- report-writing duration where observable;
- candidates processed per second;
- failure row count; and
- process exit status.

Report all three measurements, their median, the expanded-to-baseline wall-time
ratio, and the throughput change. Stage timings use the existing timestamped
progress messages; overall resource measurements use the host timing utility.

A benchmark is invalid if a run exits nonzero, uses a different candidate file,
uses a worker count other than 16, or overlaps with another benchmark run.

## Repository Integration

All work occurs on `feature/expand-patent-sequences`. Do not push, merge, tag, or
modify `main`.

After the benchmark succeeds:

1. Add `zhiyaobang_patent_seq_cleaned.xlsx`.
2. Replace the packaged `positive.csv` with the 307 cleaned records.
3. Add a benchmark report under `docs/performance/` containing environment,
   commands, raw run values, medians, and interpretation.
4. Update `README.md` with the new library counts and measured 16-core
   performance.
5. Update or add tests for the new data invariants.

The original untracked `zhiyaobang_patent_seq.xlsx` is not modified or committed
unless separately requested.

## Verification

Before integration is considered complete:

- confirm the source workbook hash has not changed;
- reopen the cleaned workbook and confirm both worksheets and expected record
  counts;
- confirm all cleaned names and normalized `(VH, VL)` pairs are unique;
- load all 307 CSV records through `load_positive_library`;
- run all unit tests;
- run external-tool integration tests in the Docker environment;
- run the CLI against the fixed 50-VHH benchmark input with both libraries;
- confirm all benchmark executions exit successfully; and
- review the Git diff and staged binary/file list before any commit.

If the expanded benchmark is operationally unacceptable, preserve the measured
result and design a separate optimization. Candidate optimizations include
pre-numbering/caching immutable positive references, deduplicating identical CDR
comparisons internally, or replacing per-pair MUSCLE process launches. Those
changes are outside this expansion design so they do not confound the baseline.

## Error Handling and Rollback

Any workbook invariant failure, ANARCI failure, benchmark nonzero exit, or
unexpected result-count change stops promotion of the expanded CSV. The current
48-record `positive.csv` remains recoverable from Git. Temporary OpenClaw files
and images must use task-specific paths and names so they cannot overwrite
unrelated server data.
