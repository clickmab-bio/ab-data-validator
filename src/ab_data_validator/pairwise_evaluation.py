from __future__ import annotations

import csv
import json
import threading
from dataclasses import asdict, dataclass, fields
from math import fsum, isclose, isfinite
from pathlib import Path

from ab_data_validator.biopython_pairwise import (
    BiopythonGlobalAligner,
    PairwiseConfig,
    PairwiseObservation,
)
from ab_data_validator.similarity import is_high_identity
from ab_data_validator.validation import IdentityComparison


GAP_CONFIGS = (
    (5.0, 0.5),
    (8.0, 1.0),
    (9.0, 1.0),
    (10.0, 0.5),
    (10.0, 1.0),
    (11.0, 1.0),
    (12.0, 1.0),
    (15.0, 2.0),
)
DEFAULT_CONFIGS = tuple(
    PairwiseConfig(matrix, gap_open, gap_extend)
    for matrix in ("BLOSUM62", "PAM30")
    for gap_open, gap_extend in GAP_CONFIGS
)

_IDENTITY_ABSOLUTE_TOLERANCE = 1e-12


@dataclass(frozen=True)
class DifferenceRecord:
    candidate_name: str
    positive_name: str
    cdr_name: str
    candidate_cdr: str
    positive_cdr: str
    config_key: str
    muscle_identity: float
    biopython_identity: float
    biopython_min_identity: float
    biopython_max_identity: float
    muscle_high: bool
    biopython_high: bool
    false_negative: bool
    threshold_ambiguous: bool
    optimal_alignment_count: int | None
    enumerated_alignment_count: int
    truncated: bool
    muscle_aligned_candidate: str
    muscle_aligned_positive: str
    biopython_aligned_candidate: str
    biopython_aligned_positive: str


@dataclass
class _ConfigurationStatistics:
    absolute_errors: list[float]
    comparison_count: int = 0
    threshold_disagreement_count: int = 0
    false_negative_count: int = 0
    threshold_ambiguous_count: int = 0
    multi_optimal_count: int = 0
    truncated_count: int = 0


class ShadowEvaluator:
    def __init__(
        self,
        *,
        configs: tuple[PairwiseConfig, ...],
        threshold: float,
        max_optimal_alignments: int,
    ) -> None:
        if not configs:
            raise ValueError("configs must not be empty")
        config_keys = [config.key for config in configs]
        if len(set(config_keys)) != len(config_keys):
            raise ValueError("config keys must be unique")
        if not isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be finite and between 0 and 1")
        if max_optimal_alignments < 1:
            raise ValueError(
                "max_optimal_alignments must be greater than or equal to 1"
            )

        self.configs = configs
        self.threshold = threshold
        self.max_optimal_alignments = max_optimal_alignments
        self._config_order = {
            config.key: order for order, config in enumerate(configs)
        }
        self._statistics = {
            config.key: _ConfigurationStatistics(absolute_errors=[])
            for config in configs
        }
        self._differences: list[DifferenceRecord] = []
        self._thread_local = threading.local()
        self._lock = threading.Lock()

    def _observe(
        self,
        config: PairwiseConfig,
        candidate_cdr: str,
        positive_cdr: str,
    ) -> PairwiseObservation:
        aligners = getattr(self._thread_local, "aligners", None)
        if aligners is None:
            aligners = {}
            self._thread_local.aligners = aligners
        aligner = aligners.get(config.key)
        if aligner is None:
            aligner = BiopythonGlobalAligner(config)
            aligners[config.key] = aligner
        return aligner.observe(
            candidate_cdr,
            positive_cdr,
            max_optimal_alignments=self.max_optimal_alignments,
        )

    def observe(
        self,
        comparison: IdentityComparison,
        muscle_alignment: tuple[str, str],
        muscle_identity: float,
    ) -> None:
        muscle_aligned_candidate, muscle_aligned_positive = muscle_alignment
        muscle_high = is_high_identity(
            muscle_identity,
            threshold=self.threshold,
        )

        outcomes: list[
            tuple[
                PairwiseConfig,
                PairwiseObservation,
                float,
                bool,
                bool,
                bool,
                bool,
                bool,
                DifferenceRecord | None,
            ]
        ] = []
        for config in self.configs:
            observation = self._observe(
                config,
                comparison.candidate_cdr,
                comparison.positive_cdr,
            )
            absolute_error = abs(
                muscle_identity - observation.first_identity
            )
            biopython_high = is_high_identity(
                observation.first_identity,
                threshold=self.threshold,
            )
            threshold_disagreement = muscle_high != biopython_high
            false_negative = muscle_high and not biopython_high
            threshold_ambiguous = (
                observation.min_identity
                < self.threshold
                <= observation.max_identity
            )
            multi_optimal = (
                (
                    observation.optimal_alignment_count is not None
                    and observation.optimal_alignment_count > 1
                )
                or observation.enumerated_alignment_count > 1
            )
            identity_different = not isclose(
                muscle_identity,
                observation.first_identity,
                rel_tol=0.0,
                abs_tol=_IDENTITY_ABSOLUTE_TOLERANCE,
            )
            difference = None
            if (
                identity_different
                or multi_optimal
                or observation.truncated
                or threshold_disagreement
                or threshold_ambiguous
            ):
                difference = DifferenceRecord(
                    candidate_name=comparison.candidate_name,
                    positive_name=comparison.positive_name,
                    cdr_name=comparison.cdr_name,
                    candidate_cdr=comparison.candidate_cdr,
                    positive_cdr=comparison.positive_cdr,
                    config_key=config.key,
                    muscle_identity=muscle_identity,
                    biopython_identity=observation.first_identity,
                    biopython_min_identity=observation.min_identity,
                    biopython_max_identity=observation.max_identity,
                    muscle_high=muscle_high,
                    biopython_high=biopython_high,
                    false_negative=false_negative,
                    threshold_ambiguous=threshold_ambiguous,
                    optimal_alignment_count=(
                        observation.optimal_alignment_count
                    ),
                    enumerated_alignment_count=(
                        observation.enumerated_alignment_count
                    ),
                    truncated=observation.truncated,
                    muscle_aligned_candidate=muscle_aligned_candidate,
                    muscle_aligned_positive=muscle_aligned_positive,
                    biopython_aligned_candidate=(
                        observation.first_aligned_candidate
                    ),
                    biopython_aligned_positive=(
                        observation.first_aligned_positive
                    ),
                )
            outcomes.append(
                (
                    config,
                    observation,
                    absolute_error,
                    threshold_disagreement,
                    false_negative,
                    threshold_ambiguous,
                    multi_optimal,
                    observation.truncated,
                    difference,
                )
            )

        with self._lock:
            for (
                config,
                _observation,
                absolute_error,
                threshold_disagreement,
                false_negative,
                threshold_ambiguous,
                multi_optimal,
                truncated,
                difference,
            ) in outcomes:
                statistics = self._statistics[config.key]
                statistics.comparison_count += 1
                statistics.absolute_errors.append(absolute_error)
                statistics.threshold_disagreement_count += int(
                    threshold_disagreement
                )
                statistics.false_negative_count += int(false_negative)
                statistics.threshold_ambiguous_count += int(
                    threshold_ambiguous
                )
                statistics.multi_optimal_count += int(multi_optimal)
                statistics.truncated_count += int(truncated)
                if difference is not None:
                    self._differences.append(difference)

    def _configuration_outcomes(self) -> list[dict[str, object]]:
        with self._lock:
            snapshots = [
                (
                    config,
                    self._config_order[config.key],
                    tuple(self._statistics[config.key].absolute_errors),
                    self._statistics[config.key].comparison_count,
                    self._statistics[
                        config.key
                    ].threshold_disagreement_count,
                    self._statistics[config.key].false_negative_count,
                    self._statistics[
                        config.key
                    ].threshold_ambiguous_count,
                    self._statistics[config.key].multi_optimal_count,
                    self._statistics[config.key].truncated_count,
                )
                for config in self.configs
            ]

        outcomes: list[dict[str, object]] = []
        for (
            config,
            config_order,
            errors,
            comparison_count,
            threshold_disagreement_count,
            false_negative_count,
            threshold_ambiguous_count,
            multi_optimal_count,
            truncated_count,
        ) in snapshots:
            total_absolute_error = fsum(sorted(errors))
            mean_absolute_error = (
                total_absolute_error / comparison_count
                if comparison_count
                else 0.0
            )
            max_absolute_error = max(errors, default=0.0)
            gate_passed = (
                threshold_disagreement_count == 0
                and false_negative_count == 0
                and threshold_ambiguous_count == 0
                and truncated_count == 0
            )
            outcomes.append(
                {
                    "config_key": config.key,
                    "matrix": config.matrix,
                    "gap_open": config.gap_open,
                    "gap_extend": config.gap_extend,
                    "config_order": config_order,
                    "comparison_count": comparison_count,
                    "total_absolute_error": total_absolute_error,
                    "mean_absolute_error": mean_absolute_error,
                    "max_absolute_error": max_absolute_error,
                    "threshold_disagreement_count": (
                        threshold_disagreement_count
                    ),
                    "false_negative_count": false_negative_count,
                    "threshold_ambiguous_count": threshold_ambiguous_count,
                    "multi_optimal_count": multi_optimal_count,
                    "truncated_count": truncated_count,
                    "gate_passed": gate_passed,
                }
            )
        return outcomes

    def summary(self) -> dict[str, object]:
        return {
            "threshold": self.threshold,
            "max_optimal_alignments": self.max_optimal_alignments,
            "configurations": self._configuration_outcomes(),
        }

    def best_passing_config(self) -> PairwiseConfig | None:
        passing_outcomes = [
            outcome
            for outcome in self._configuration_outcomes()
            if outcome["gate_passed"]
        ]
        if not passing_outcomes:
            return None
        best = min(
            passing_outcomes,
            key=lambda outcome: (
                not outcome["gate_passed"],
                outcome["max_absolute_error"],
                outcome["mean_absolute_error"],
                outcome["multi_optimal_count"],
                outcome["config_order"],
            ),
        )
        return self.configs[int(best["config_order"])]

    def write(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_text = json.dumps(
            self.summary(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        (output_dir / "summary.json").write_text(
            summary_text + "\n",
            encoding="utf-8",
        )

        with self._lock:
            differences = sorted(
                self._differences,
                key=lambda record: (
                    record.candidate_name,
                    record.positive_name,
                    record.cdr_name,
                    record.config_key,
                ),
            )
        field_names = [field.name for field in fields(DifferenceRecord)]
        with (output_dir / "differences.csv").open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=field_names)
            writer.writeheader()
            writer.writerows(asdict(record) for record in differences)
