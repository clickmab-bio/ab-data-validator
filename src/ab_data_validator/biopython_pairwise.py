from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from math import isfinite

from Bio import Align
from Bio.Align import substitution_matrices

from ab_data_validator.similarity import calculate_identity


@dataclass(frozen=True, order=True)
class PairwiseConfig:
    matrix: str
    gap_open: float
    gap_extend: float

    def __post_init__(self) -> None:
        if not isfinite(self.gap_open) or self.gap_open <= 0:
            raise ValueError("gap_open must be finite and greater than 0")
        if not isfinite(self.gap_extend) or self.gap_extend <= 0:
            raise ValueError("gap_extend must be finite and greater than 0")

    @property
    def key(self) -> str:
        return (
            f"{self.matrix}-open{self.gap_open:g}"
            f"-extend{self.gap_extend:g}"
        )


@dataclass(frozen=True)
class PairwiseObservation:
    first_aligned_candidate: str
    first_aligned_positive: str
    first_identity: float
    min_identity: float
    max_identity: float
    optimal_alignment_count: int | None
    enumerated_alignment_count: int
    truncated: bool


class BiopythonGlobalAligner:
    def __init__(self, config: PairwiseConfig) -> None:
        try:
            substitution_matrix = substitution_matrices.load(config.matrix)
        except (FileNotFoundError, KeyError, ValueError) as error:
            raise ValueError(
                f"unknown substitution matrix: {config.matrix}"
            ) from error

        aligner = Align.PairwiseAligner()
        aligner.mode = "global"
        aligner.substitution_matrix = substitution_matrix
        aligner.open_gap_score = -config.gap_open
        aligner.extend_gap_score = -config.gap_extend

        self.config = config
        self._aligner = aligner

    def observe(
        self,
        candidate: str,
        positive: str,
        *,
        max_optimal_alignments: int,
    ) -> PairwiseObservation:
        if max_optimal_alignments < 1:
            raise ValueError(
                "max_optimal_alignments must be greater than or equal to 1"
            )

        alignments = self._aligner.align(candidate, positive)
        try:
            optimal_alignment_count: int | None = len(alignments)
        except OverflowError:
            optimal_alignment_count = None

        observed_alignments = list(
            islice(alignments, max_optimal_alignments)
        )
        if not observed_alignments:
            raise ValueError("pairwise alignment produced no alignments")

        aligned_pairs = [
            (str(alignment[0]), str(alignment[1]))
            for alignment in observed_alignments
        ]
        identities = [
            calculate_identity(aligned_candidate, aligned_positive)
            for aligned_candidate, aligned_positive in aligned_pairs
        ]
        first_aligned_candidate, first_aligned_positive = aligned_pairs[0]
        enumerated_alignment_count = len(observed_alignments)
        truncated = (
            optimal_alignment_count is None
            or optimal_alignment_count > enumerated_alignment_count
        )

        return PairwiseObservation(
            first_aligned_candidate=first_aligned_candidate,
            first_aligned_positive=first_aligned_positive,
            first_identity=identities[0],
            min_identity=min(identities),
            max_identity=max(identities),
            optimal_alignment_count=optimal_alignment_count,
            enumerated_alignment_count=enumerated_alignment_count,
            truncated=truncated,
        )

    def align(
        self,
        cdr_name: str,
        candidate_cdr: str,
        positive_cdr: str,
    ) -> tuple[str, str]:
        del cdr_name
        observation = self.observe(
            candidate_cdr,
            positive_cdr,
            max_optimal_alignments=1,
        )
        return (
            observation.first_aligned_candidate,
            observation.first_aligned_positive,
        )
