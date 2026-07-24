from dataclasses import FrozenInstanceError

import pytest


pytest.importorskip("Bio", minversion="1.87")

from ab_data_validator.biopython_pairwise import (  # noqa: E402
    BiopythonGlobalAligner,
    PairwiseConfig,
)


def test_blosum62_global_alignment_observation() -> None:
    aligner = BiopythonGlobalAligner(PairwiseConfig("BLOSUM62", 10.0, 0.5))

    observation = aligner.observe("ARDY", "ARDYG")

    assert observation.first_aligned_candidate == "ARDY-"
    assert observation.first_aligned_positive == "ARDYG"
    assert observation.first_identity == pytest.approx(0.8)
    assert observation.min_identity == pytest.approx(0.8)
    assert observation.max_identity == pytest.approx(0.8)
    assert observation.optimal_alignment_count == 1
    assert observation.enumerated_alignment_count == 1
    assert observation.truncated is False


def test_pam30_global_alignment_exact_match() -> None:
    aligner = BiopythonGlobalAligner(PairwiseConfig("PAM30", 9.0, 1.0))

    observation = aligner.observe("ARDY", "ARDY")

    assert observation.first_identity == pytest.approx(1.0)
    assert observation.min_identity == pytest.approx(1.0)
    assert observation.max_identity == pytest.approx(1.0)


def test_pairwise_config_is_frozen_ordered_and_has_stable_key() -> None:
    config = PairwiseConfig("BLOSUM62", 10.0, 0.5)

    assert config.key == "BLOSUM62-open10-extend0.5"
    assert config < PairwiseConfig("PAM30", 9.0, 1.0)
    with pytest.raises(FrozenInstanceError):
        config.gap_open = 11.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("gap_open", "gap_extend", "message"),
    [
        (0.0, 0.5, "gap_open must be greater than 0"),
        (-1.0, 0.5, "gap_open must be greater than 0"),
        (float("nan"), 0.5, "gap_open must be greater than 0"),
        (10.0, 0.0, "gap_extend must be greater than 0"),
        (10.0, -1.0, "gap_extend must be greater than 0"),
        (10.0, float("nan"), "gap_extend must be greater than 0"),
    ],
)
def test_gap_penalties_must_be_positive(
    gap_open: float,
    gap_extend: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PairwiseConfig("BLOSUM62", gap_open, gap_extend)


def test_unknown_substitution_matrix_has_clear_error() -> None:
    with pytest.raises(ValueError, match="unknown substitution matrix"):
        BiopythonGlobalAligner(PairwiseConfig("NOT_A_MATRIX", 10.0, 0.5))


class _FakeAlignments:
    def __init__(self, count: int) -> None:
        self.count = count

    def __len__(self) -> int:
        return self.count

    def __iter__(self):
        for _ in range(self.count):
            yield ("ARDY", "ARDY")


class _OverflowingAlignments(_FakeAlignments):
    def __len__(self) -> int:
        raise OverflowError


class _FakePairwiseAligner:
    def __init__(self, alignments: _FakeAlignments) -> None:
        self.alignments = alignments

    def align(self, candidate: str, positive: str) -> _FakeAlignments:
        del candidate, positive
        return self.alignments


def test_observation_caps_enumeration_and_reports_truncation(monkeypatch) -> None:
    aligner = BiopythonGlobalAligner(
        PairwiseConfig("BLOSUM62", 10.0, 0.5),
        max_optimal_alignments=1000,
    )
    monkeypatch.setattr(aligner, "_aligner", _FakePairwiseAligner(_FakeAlignments(2000)))

    observation = aligner.observe("ARDY", "ARDY")

    assert observation.optimal_alignment_count == 2000
    assert observation.enumerated_alignment_count == 1000
    assert observation.truncated is True


def test_overflowing_alignment_count_is_unknown_and_truncated(monkeypatch) -> None:
    aligner = BiopythonGlobalAligner(
        PairwiseConfig("BLOSUM62", 10.0, 0.5),
        max_optimal_alignments=2,
    )
    monkeypatch.setattr(
        aligner,
        "_aligner",
        _FakePairwiseAligner(_OverflowingAlignments(3)),
    )

    observation = aligner.observe("ARDY", "ARDY")

    assert observation.optimal_alignment_count is None
    assert observation.enumerated_alignment_count == 2
    assert observation.truncated is True


def test_max_optimal_alignments_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match="max_optimal_alignments must be greater than or equal to 1",
    ):
        BiopythonGlobalAligner(
            PairwiseConfig("BLOSUM62", 10.0, 0.5),
            max_optimal_alignments=0,
        )


def test_observe_rejects_empty_alignment_results(monkeypatch) -> None:
    aligner = BiopythonGlobalAligner(PairwiseConfig("BLOSUM62", 10.0, 0.5))
    monkeypatch.setattr(aligner, "_aligner", _FakePairwiseAligner(_FakeAlignments(0)))

    with pytest.raises(ValueError, match="pairwise alignment produced no alignments"):
        aligner.observe("ARDY", "ARDY")


def test_align_adapts_first_alignment_to_aligner_protocol() -> None:
    aligner = BiopythonGlobalAligner(PairwiseConfig("BLOSUM62", 10.0, 0.5))

    aligned_candidate, aligned_positive = aligner.align("HCDR3", "ARDY", "ARDYG")

    assert aligned_candidate == "ARDY-"
    assert aligned_positive == "ARDYG"
