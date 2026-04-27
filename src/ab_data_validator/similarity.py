from __future__ import annotations


def calculate_identity(aligned_a: str, aligned_b: str) -> float:
    if len(aligned_a) != len(aligned_b):
        raise ValueError("sequences must have the same aligned length")

    comparable_columns = 0
    matches = 0
    for residue_a, residue_b in zip(aligned_a, aligned_b, strict=True):
        if residue_a == "-" and residue_b == "-":
            continue
        comparable_columns += 1
        if residue_a == residue_b:
            matches += 1

    if comparable_columns == 0:
        raise ValueError("alignment has no comparable columns")
    return matches / comparable_columns


def is_high_identity(identity: float, *, threshold: float) -> bool:
    return identity >= threshold
