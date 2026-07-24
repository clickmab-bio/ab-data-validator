from __future__ import annotations

import threading

import Bio

from ab_data_validator.biopython_pairwise import BiopythonGlobalAligner, PairwiseConfig
from ab_data_validator.muscle import align_pair


DEFAULT_ALIGNER = "pairwise"
SUPPORTED_ALIGNERS = ("pairwise", "muscle")
PRODUCTION_PAIRWISE_CONFIG = PairwiseConfig(
    matrix="BLOSUM62",
    gap_open=11.0,
    gap_extend=1.0,
)


class AlignmentBackendError(RuntimeError):
    pass


class MuscleAligner:
    def __init__(self, *, muscle_bin: str = "muscle") -> None:
        self.muscle_bin = muscle_bin

    def align(
        self,
        cdr_name: str,
        candidate_cdr: str,
        positive_cdr: str,
    ) -> tuple[str, str]:
        del cdr_name
        return align_pair(candidate_cdr, positive_cdr, muscle_bin=self.muscle_bin)


class ThreadLocalPairwiseAligner:
    def __init__(self, config: PairwiseConfig = PRODUCTION_PAIRWISE_CONFIG) -> None:
        self.config = config
        self._local = threading.local()

    def align(
        self,
        cdr_name: str,
        candidate_cdr: str,
        positive_cdr: str,
    ) -> tuple[str, str]:
        try:
            return self._get_aligner().align(
                cdr_name,
                candidate_cdr,
                positive_cdr,
            )
        except ValueError as error:
            raise AlignmentBackendError(
                f"Pairwise alignment failed for {cdr_name}: {error}"
            ) from error

    def _get_aligner(self) -> BiopythonGlobalAligner:
        aligner = getattr(self._local, "aligner", None)
        if aligner is None:
            aligner = BiopythonGlobalAligner(self.config)
            self._local.aligner = aligner
        return aligner


def create_production_aligner(
    backend: str = DEFAULT_ALIGNER,
    *,
    muscle_bin: str = "muscle",
) -> ThreadLocalPairwiseAligner | MuscleAligner:
    if backend == "pairwise":
        return ThreadLocalPairwiseAligner()
    if backend == "muscle":
        return MuscleAligner(muscle_bin=muscle_bin)
    raise ValueError(f"unsupported alignment backend: {backend}")


def describe_production_aligner(
    backend: str,
    *,
    muscle_bin: str = "muscle",
) -> str:
    if backend == "pairwise":
        config = PRODUCTION_PAIRWISE_CONFIG
        return (
            "aligner=pairwise "
            f"biopython={Bio.__version__} "
            f"matrix={config.matrix} "
            f"gap_open={config.gap_open:g} "
            f"gap_extend={config.gap_extend:g}"
        )
    if backend == "muscle":
        return f"aligner=muscle executable={muscle_bin}"
    raise ValueError(f"unsupported alignment backend: {backend}")
