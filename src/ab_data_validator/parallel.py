from __future__ import annotations

import os


def available_cpu_count() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def resolve_worker_count(requested_workers: int) -> int:
    if requested_workers < 0:
        raise ValueError("workers must be greater than or equal to 0")
    if requested_workers == 0:
        return available_cpu_count()
    return requested_workers
