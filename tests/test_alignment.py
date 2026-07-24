import importlib
import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor

import Bio
import pytest


_ALIGNMENT_MODULE = "ab_data_validator.alignment"


@pytest.fixture
def alignment_module():
    if importlib.util.find_spec(_ALIGNMENT_MODULE) is None:
        pytest.skip("alignment module has not yet been implemented")
    return importlib.import_module(_ALIGNMENT_MODULE)


def test_alignment_module_is_available() -> None:
    assert importlib.util.find_spec(_ALIGNMENT_MODULE) is not None


def test_default_aligner_is_pairwise(alignment_module) -> None:
    assert alignment_module.DEFAULT_ALIGNER == "pairwise"


def test_production_pairwise_config_is_fixed(alignment_module) -> None:
    config = alignment_module.PRODUCTION_PAIRWISE_CONFIG

    assert config.matrix == "BLOSUM62"
    assert config.gap_open == 11.0
    assert config.gap_extend == 1.0


def test_factory_creates_thread_local_pairwise_aligner(alignment_module) -> None:
    aligner = alignment_module.create_production_aligner("pairwise")

    assert isinstance(aligner, alignment_module.ThreadLocalPairwiseAligner)


def test_factory_creates_muscle_aligner_with_selected_binary(alignment_module) -> None:
    aligner = alignment_module.create_production_aligner(
        "muscle", muscle_bin="muscle5"
    )

    assert isinstance(aligner, alignment_module.MuscleAligner)
    assert aligner.muscle_bin == "muscle5"


def test_pairwise_description_is_reproducible(alignment_module) -> None:
    description = alignment_module.describe_production_aligner("pairwise")

    assert Bio.__version__ == "1.87"
    assert "aligner=pairwise" in description
    assert "biopython=1.87" in description
    assert "matrix=BLOSUM62" in description
    assert "gap_open=11" in description
    assert "gap_extend=1" in description


def test_pairwise_aligner_uses_one_backend_per_worker_thread(
    monkeypatch, alignment_module
) -> None:
    created_backends = []

    class FakeBiopythonGlobalAligner:
        def __init__(self, config) -> None:
            self.config = config
            created_backends.append(self)

        def align(self, cdr_name: str, candidate_cdr: str, positive_cdr: str):
            del cdr_name
            return candidate_cdr, positive_cdr

    monkeypatch.setattr(
        alignment_module, "BiopythonGlobalAligner", FakeBiopythonGlobalAligner
    )
    aligner = alignment_module.ThreadLocalPairwiseAligner()
    barrier = threading.Barrier(2)

    def align_in_worker(candidate_cdr: str) -> tuple[str, str]:
        barrier.wait()
        first_result = aligner.align("CDRH3", candidate_cdr, "positive")
        assert aligner.align("CDRH3", candidate_cdr, "positive") == first_result
        return first_result

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(align_in_worker, "candidate-one"),
            executor.submit(align_in_worker, "candidate-two"),
        ]
        results = [future.result() for future in futures]

    assert results == [
        ("candidate-one", "positive"),
        ("candidate-two", "positive"),
    ]
    assert len(created_backends) == 2
    assert created_backends[0] is not created_backends[1]


def test_pairwise_errors_do_not_fall_back_to_muscle(
    monkeypatch, alignment_module
) -> None:
    class FailingBiopythonGlobalAligner:
        def __init__(self, config) -> None:
            del config

        def align(self, cdr_name: str, candidate_cdr: str, positive_cdr: str):
            del cdr_name, candidate_cdr, positive_cdr
            raise ValueError("no alignment")

    def muscle_must_not_run(*args, **kwargs):
        del args, kwargs
        raise AssertionError("MUSCLE fallback must not run")

    monkeypatch.setattr(
        alignment_module, "BiopythonGlobalAligner", FailingBiopythonGlobalAligner
    )
    monkeypatch.setattr(alignment_module, "align_pair", muscle_must_not_run)
    aligner = alignment_module.ThreadLocalPairwiseAligner()

    with pytest.raises(
        alignment_module.AlignmentBackendError,
        match="Pairwise alignment failed for CDRH3",
    ) as error_info:
        aligner.align("CDRH3", "candidate", "positive")

    assert isinstance(error_info.value.__cause__, ValueError)
    assert str(error_info.value.__cause__) == "no alignment"


def test_factory_rejects_unknown_backend(alignment_module) -> None:
    with pytest.raises(ValueError, match="unsupported alignment backend: unknown"):
        alignment_module.create_production_aligner("unknown")
