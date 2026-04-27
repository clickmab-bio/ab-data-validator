import pytest

from ab_data_validator.similarity import calculate_identity, is_high_identity


def test_exact_aligned_match_has_identity_one():
    assert calculate_identity("ARDY", "ARDY") == 1.0


def test_mismatch_lowers_identity():
    assert calculate_identity("ARDY", "ARDF") == 0.75


def test_gap_counts_in_denominator_and_as_mismatch():
    assert calculate_identity("ARDY-", "ARDYG") == 0.8


def test_double_gap_columns_are_ignored():
    assert calculate_identity("AR-DY-", "AR-DYG") == 0.8


def test_identity_requires_equal_aligned_lengths():
    with pytest.raises(ValueError, match="same aligned length"):
        calculate_identity("ARDY", "ARD")


def test_high_identity_fails_at_threshold_boundary():
    assert is_high_identity(0.8, threshold=0.8)


def test_identity_below_threshold_passes():
    assert not is_high_identity(0.7999, threshold=0.8)
