from __future__ import annotations

import csv
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields

import pytest

from ab_data_validator.biopython_pairwise import PairwiseConfig, PairwiseObservation
from ab_data_validator.models import InputType
from ab_data_validator.pairwise_evaluation import (
    DEFAULT_CONFIGS,
    GAP_CONFIGS,
    DifferenceRecord,
    ShadowEvaluator,
)
from ab_data_validator.validation import IdentityComparison


def _comparison(
    *,
    candidate_name: str = "CandidateA",
    positive_name: str = "PositiveA",
    cdr_name: str = "HCDR3",
    candidate_cdr: str = "ARDY",
    positive_cdr: str = "ARDYG",
) -> IdentityComparison:
    return IdentityComparison(
        candidate_name=candidate_name,
        candidate_input_type=InputType.NANOBODY,
        cdr_name=cdr_name,
        candidate_cdr=candidate_cdr,
        positive_name=positive_name,
        positive_cdr=positive_cdr,
    )


def _observation(
    *,
    identity: float = 0.8,
    min_identity: float | None = None,
    max_identity: float | None = None,
    optimal_alignment_count: int | None = 1,
    enumerated_alignment_count: int = 1,
    truncated: bool = False,
    aligned_candidate: str = "ARDY-",
    aligned_positive: str = "ARDYG",
) -> PairwiseObservation:
    return PairwiseObservation(
        first_aligned_candidate=aligned_candidate,
        first_aligned_positive=aligned_positive,
        first_identity=identity,
        min_identity=identity if min_identity is None else min_identity,
        max_identity=identity if max_identity is None else max_identity,
        optimal_alignment_count=optimal_alignment_count,
        enumerated_alignment_count=enumerated_alignment_count,
        truncated=truncated,
    )


def test_default_grid_contains_sixteen_unique_configurations() -> None:
    assert GAP_CONFIGS == (
        (5.0, 0.5),
        (8.0, 1.0),
        (9.0, 1.0),
        (10.0, 0.5),
        (10.0, 1.0),
        (11.0, 1.0),
        (12.0, 1.0),
        (15.0, 2.0),
    )
    assert len(DEFAULT_CONFIGS) == 16
    assert len({config.key for config in DEFAULT_CONFIGS}) == 16
    assert [config.matrix for config in DEFAULT_CONFIGS[:8]] == ["BLOSUM62"] * 8
    assert [config.matrix for config in DEFAULT_CONFIGS[8:]] == ["PAM30"] * 8


def test_difference_record_has_stable_field_order() -> None:
    assert [field.name for field in fields(DifferenceRecord)] == [
        "candidate_name",
        "positive_name",
        "cdr_name",
        "candidate_cdr",
        "positive_cdr",
        "config_key",
        "muscle_identity",
        "biopython_identity",
        "biopython_min_identity",
        "biopython_max_identity",
        "muscle_high",
        "biopython_high",
        "false_negative",
        "threshold_ambiguous",
        "optimal_alignment_count",
        "enumerated_alignment_count",
        "truncated",
        "muscle_aligned_candidate",
        "muscle_aligned_positive",
        "biopython_aligned_candidate",
        "biopython_aligned_positive",
    ]


@pytest.mark.parametrize(
    ("configs", "threshold", "maximum", "message"),
    [
        ((), 0.8, 1, "configs must not be empty"),
        ((DEFAULT_CONFIGS[0], DEFAULT_CONFIGS[0]), 0.8, 1, "unique"),
        ((DEFAULT_CONFIGS[0],), -0.1, 1, "threshold"),
        ((DEFAULT_CONFIGS[0],), 1.1, 1, "threshold"),
        ((DEFAULT_CONFIGS[0],), float("nan"), 1, "threshold"),
        ((DEFAULT_CONFIGS[0],), float("inf"), 1, "threshold"),
        ((DEFAULT_CONFIGS[0],), 0.8, 1.5, "positive integer"),
        ((DEFAULT_CONFIGS[0],), 0.8, True, "positive integer"),
        ((DEFAULT_CONFIGS[0],), 0.8, False, "positive integer"),
        ((DEFAULT_CONFIGS[0],), 0.8, float("nan"), "positive integer"),
        ((DEFAULT_CONFIGS[0],), 0.8, float("inf"), "positive integer"),
        ((DEFAULT_CONFIGS[0],), 0.8, float("-inf"), "positive integer"),
        ((DEFAULT_CONFIGS[0],), 0.8, 0, "positive integer"),
        ((DEFAULT_CONFIGS[0],), 0.8, -1, "positive integer"),
    ],
)
def test_constructor_validates_inputs(
    configs: tuple[PairwiseConfig, ...],
    threshold: float,
    maximum: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ShadowEvaluator(
            configs=configs,
            threshold=threshold,
            max_optimal_alignments=maximum,  # type: ignore[arg-type]
        )


def test_shadow_evaluator_records_threshold_difference_and_false_negative(
    monkeypatch,
) -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:1],
        threshold=0.8,
        max_optimal_alignments=1000,
    )
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(identity=0.79),
    )

    evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 0.8)

    outcome = evaluator.summary()["configurations"][0]
    assert outcome["comparison_count"] == 1
    assert outcome["total_absolute_error"] == pytest.approx(0.01)
    assert outcome["mean_absolute_error"] == pytest.approx(0.01)
    assert outcome["max_absolute_error"] == pytest.approx(0.01)
    assert outcome["threshold_disagreement_count"] == 1
    assert outcome["false_negative_count"] == 1
    assert outcome["gate_passed"] is False
    assert evaluator.best_passing_config() is None


def test_empty_evaluator_keeps_gate_formula_but_has_no_best_config() -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:1],
        threshold=0.8,
        max_optimal_alignments=1000,
    )

    outcome = evaluator.summary()["configurations"][0]

    assert outcome["comparison_count"] == 0
    assert outcome["gate_passed"] is True
    assert evaluator.best_passing_config() is None


def test_multi_optimal_truncated_and_ambiguous_are_counted(monkeypatch) -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:1],
        threshold=0.8,
        max_optimal_alignments=2,
    )
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(
            identity=0.8,
            min_identity=0.75,
            max_identity=0.85,
            optimal_alignment_count=3,
            enumerated_alignment_count=2,
            truncated=True,
        ),
    )

    evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 0.8)

    outcome = evaluator.summary()["configurations"][0]
    assert outcome["threshold_ambiguous_count"] == 1
    assert outcome["multi_optimal_count"] == 1
    assert outcome["truncated_count"] == 1
    assert outcome["gate_passed"] is False


def test_unknown_optimal_count_is_treated_as_multi_optimal(
    tmp_path,
    monkeypatch,
) -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:1],
        threshold=0.8,
        max_optimal_alignments=1,
    )
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(
            optimal_alignment_count=None,
            enumerated_alignment_count=1,
            truncated=False,
        ),
    )

    evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 0.8)
    evaluator.write(tmp_path)

    outcome = evaluator.summary()["configurations"][0]
    assert outcome["multi_optimal_count"] == 1
    with (tmp_path / "differences.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["optimal_alignment_count"] == ""
    assert rows[0]["truncated"] == "False"


def test_best_passing_config_uses_smallest_maximum_error(monkeypatch) -> None:
    configs = DEFAULT_CONFIGS[:2]
    evaluator = ShadowEvaluator(
        configs=configs,
        threshold=0.8,
        max_optimal_alignments=1000,
    )
    identities = {configs[0].key: 0.88, configs[1].key: 0.895}
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(
            identity=identities[config.key]
        ),
    )

    evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 0.9)

    assert evaluator.best_passing_config() == configs[1]


def test_best_passing_config_ignores_configs_without_comparisons(
    monkeypatch,
) -> None:
    configs = DEFAULT_CONFIGS[:2]
    evaluator = ShadowEvaluator(
        configs=configs,
        threshold=0.8,
        max_optimal_alignments=1000,
    )
    identities = {configs[0].key: 0.9, configs[1].key: 0.89}
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(
            identity=identities[config.key]
        ),
    )
    evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 0.9)
    with evaluator._lock:
        empty_statistics = evaluator._statistics[configs[0].key]
        empty_statistics.comparison_count = 0
        empty_statistics.absolute_errors.clear()

    assert evaluator.best_passing_config() == configs[1]


def test_summary_preserves_config_order(monkeypatch) -> None:
    configs = (DEFAULT_CONFIGS[3], DEFAULT_CONFIGS[0], DEFAULT_CONFIGS[9])
    evaluator = ShadowEvaluator(
        configs=configs,
        threshold=0.8,
        max_optimal_alignments=1000,
    )
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(),
    )

    evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 0.8)

    assert [
        outcome["config_key"]
        for outcome in evaluator.summary()["configurations"]
    ] == [config.key for config in configs]


def test_shadow_output_is_stably_sorted_and_parseable(tmp_path, monkeypatch) -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:1],
        threshold=0.8,
        max_optimal_alignments=1000,
    )
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(identity=0.75),
    )
    later = _comparison(candidate_name="CandidateB", positive_name="PositiveB")
    earlier = _comparison(
        candidate_name="CandidateA",
        positive_name="PositiveA",
        cdr_name="HCDR1",
    )

    evaluator.observe(later, ("ARDY-", "ARDYG"), 1.0)
    evaluator.observe(earlier, ("ARDY-", "ARDYG"), 1.0)
    evaluator.write(tmp_path)

    summary_text = (tmp_path / "summary.json").read_text(encoding="utf-8")
    payload = json.loads(summary_text)
    with (tmp_path / "differences.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert payload["threshold"] == 0.8
    assert payload["max_optimal_alignments"] == 1000
    assert summary_text.endswith("\n")
    assert [row["candidate_name"] for row in rows] == [
        "CandidateA",
        "CandidateB",
    ]
    assert list(rows[0]) == [field.name for field in fields(DifferenceRecord)]

    first_summary = summary_text
    first_csv = (tmp_path / "differences.csv").read_text(encoding="utf-8")
    evaluator.write(tmp_path)
    assert (tmp_path / "summary.json").read_text(encoding="utf-8") == first_summary
    assert (tmp_path / "differences.csv").read_text(encoding="utf-8") == first_csv


def test_write_uses_one_snapshot_for_summary_and_differences(
    tmp_path,
    monkeypatch,
) -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:1],
        threshold=0.8,
        max_optimal_alignments=1000,
    )
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(identity=0.75),
    )
    evaluator.observe(
        _comparison(candidate_name="BeforeSnapshot"),
        ("ARDY-", "ARDYG"),
        1.0,
    )
    original_snapshot = evaluator._snapshot
    snapshot_taken = threading.Event()
    finish_write = threading.Event()

    def controlled_snapshot():
        snapshot = original_snapshot()
        snapshot_taken.set()
        assert finish_write.wait(timeout=5)
        return snapshot

    monkeypatch.setattr(evaluator, "_snapshot", controlled_snapshot)
    with ThreadPoolExecutor(max_workers=1) as executor:
        write_future = executor.submit(evaluator.write, tmp_path)
        assert snapshot_taken.wait(timeout=5)
        evaluator.observe(
            _comparison(candidate_name="AfterSnapshot"),
            ("ARDY-", "ARDYG"),
            1.0,
        )
        finish_write.set()
        write_future.result(timeout=5)

    payload = json.loads(
        (tmp_path / "summary.json").read_text(encoding="utf-8")
    )
    with (tmp_path / "differences.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert payload["configurations"][0]["comparison_count"] == 1
    assert [row["candidate_name"] for row in rows] == ["BeforeSnapshot"]


def test_concurrent_completion_order_does_not_change_report_bytes(
    tmp_path,
    monkeypatch,
) -> None:
    def run_with_completion_order(output_dir, completion_order):
        evaluator = ShadowEvaluator(
            configs=DEFAULT_CONFIGS[:1],
            threshold=0.8,
            max_optimal_alignments=1000,
        )
        sequences = ("AAAA", "ZZZZ")
        ready = {sequence: threading.Event() for sequence in sequences}
        release = {sequence: threading.Event() for sequence in sequences}

        def controlled_observe(config, candidate_cdr, positive_cdr):
            del config
            ready[candidate_cdr].set()
            assert release[candidate_cdr].wait(timeout=5)
            return _observation(
                identity=0.75,
                aligned_candidate=f"{candidate_cdr}-",
                aligned_positive=positive_cdr,
            )

        monkeypatch.setattr(evaluator, "_observe", controlled_observe)
        comparisons = {
            sequence: _comparison(
                candidate_name="SameCandidate",
                positive_name="SamePositive",
                cdr_name="HCDR3",
                candidate_cdr=sequence,
                positive_cdr=f"{sequence}P",
            )
            for sequence in sequences
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                sequence: executor.submit(
                    evaluator.observe,
                    comparisons[sequence],
                    (f"MUSCLE-{sequence}", f"MUSCLE-{sequence}P"),
                    1.0,
                )
                for sequence in sequences
            }
            assert all(event.wait(timeout=5) for event in ready.values())
            for sequence in completion_order:
                release[sequence].set()
                futures[sequence].result(timeout=5)

        evaluator.write(output_dir)
        return (
            (output_dir / "summary.json").read_bytes(),
            (output_dir / "differences.csv").read_bytes(),
        )

    first_summary, first_csv = run_with_completion_order(
        tmp_path / "first",
        ("ZZZZ", "AAAA"),
    )
    second_summary, second_csv = run_with_completion_order(
        tmp_path / "second",
        ("AAAA", "ZZZZ"),
    )

    assert first_summary == second_summary
    assert first_csv == second_csv
    rows = list(
        csv.DictReader(first_csv.decode("utf-8").splitlines())
    )
    assert [row["candidate_cdr"] for row in rows] == ["AAAA", "ZZZZ"]


def test_difference_sort_handles_unknown_and_known_alignment_counts(
    tmp_path,
    monkeypatch,
) -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:1],
        threshold=0.8,
        max_optimal_alignments=1000,
    )
    observations = iter(
        (
            _observation(identity=0.75, optimal_alignment_count=1),
            _observation(identity=0.75, optimal_alignment_count=None),
        )
    )
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: next(observations),
    )

    evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 1.0)
    evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 1.0)
    evaluator.write(tmp_path)

    with (tmp_path / "differences.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert [row["optimal_alignment_count"] for row in rows] == ["", "1"]


def test_any_nonzero_float_difference_creates_difference_record(
    tmp_path,
    monkeypatch,
) -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:1],
        threshold=0.5,
        max_optimal_alignments=1000,
    )
    identities = iter((0.9 + 5e-13, 0.9))
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(
            identity=next(identities)
        ),
    )

    evaluator.observe(
        _comparison(candidate_name="Recorded"),
        ("ARDY", "ARDY"),
        0.9,
    )
    evaluator.observe(
        _comparison(candidate_name="Identical"),
        ("ARDY", "ARDY"),
        0.9,
    )
    evaluator.write(tmp_path)

    with (tmp_path / "differences.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert [row["candidate_name"] for row in rows] == ["Recorded"]


def test_concurrent_observations_count_every_comparison(monkeypatch) -> None:
    evaluator = ShadowEvaluator(
        configs=DEFAULT_CONFIGS[:2],
        threshold=0.8,
        max_optimal_alignments=1000,
    )
    monkeypatch.setattr(
        evaluator,
        "_observe",
        lambda config, candidate_cdr, positive_cdr: _observation(),
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                lambda _: evaluator.observe(
                    _comparison(),
                    ("ARDY-", "ARDYG"),
                    0.8,
                ),
                range(100),
            )
        )

    assert [
        outcome["comparison_count"]
        for outcome in evaluator.summary()["configurations"]
    ] == [100, 100]


def test_aligner_instances_are_cached_per_thread_and_config(monkeypatch) -> None:
    configs = DEFAULT_CONFIGS[:2]
    creations: list[tuple[int, str, object]] = []
    creation_lock = threading.Lock()
    barrier = threading.Barrier(4)

    class FakeAligner:
        def __init__(self, config: PairwiseConfig) -> None:
            self.config = config
            with creation_lock:
                creations.append((threading.get_ident(), config.key, self))

        def observe(
            self,
            candidate: str,
            positive: str,
            *,
            max_optimal_alignments: int,
        ) -> PairwiseObservation:
            del candidate, positive, max_optimal_alignments
            return _observation()

    monkeypatch.setattr(
        "ab_data_validator.pairwise_evaluation.BiopythonGlobalAligner",
        FakeAligner,
    )
    evaluator = ShadowEvaluator(
        configs=configs,
        threshold=0.8,
        max_optimal_alignments=1000,
    )

    def evaluate_twice(_: int) -> None:
        barrier.wait()
        evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 0.8)
        evaluator.observe(_comparison(), ("ARDY-", "ARDYG"), 0.8)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(evaluate_twice, range(4)))

    assert len(creations) == 4 * len(configs)
    assert len(
        {(thread_id, config_key) for thread_id, config_key, _ in creations}
    ) == 4 * len(configs)
