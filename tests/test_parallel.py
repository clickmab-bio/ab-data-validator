import pytest

from ab_data_validator import parallel


def test_available_cpu_count_prefers_cpu_affinity(monkeypatch):
    monkeypatch.setattr(parallel.os, "sched_getaffinity", lambda process_id: {0, 1, 2})

    assert parallel.available_cpu_count() == 3


def test_available_cpu_count_falls_back_to_os_cpu_count(monkeypatch):
    def fail_affinity(process_id):
        raise OSError("affinity unavailable")

    monkeypatch.setattr(parallel.os, "sched_getaffinity", fail_affinity, raising=False)
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 5)

    assert parallel.available_cpu_count() == 5


def test_available_cpu_count_falls_back_to_one(monkeypatch):
    def fail_affinity(process_id):
        raise OSError("affinity unavailable")

    monkeypatch.setattr(parallel.os, "sched_getaffinity", fail_affinity, raising=False)
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: None)

    assert parallel.available_cpu_count() == 1


def test_resolve_worker_count_uses_auto_detection_for_zero(monkeypatch):
    monkeypatch.setattr(parallel, "available_cpu_count", lambda: 7)

    assert parallel.resolve_worker_count(0) == 7


def test_resolve_worker_count_rejects_negative_values():
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        parallel.resolve_worker_count(-1)
