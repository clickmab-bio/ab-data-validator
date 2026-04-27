from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NumberedResidue:
    position: int
    insertion: str
    residue: str


@dataclass(frozen=True)
class ChainCompleteness:
    missing_n_terminal: bool
    c_terminal_too_short: bool
    max_position: int | None

    @property
    def is_complete(self) -> bool:
        return not self.missing_n_terminal and not self.c_terminal_too_short


def check_chain_completeness(
    residues: list[NumberedResidue],
    *,
    required_c_terminal_position: int = 127,
) -> ChainCompleteness:
    positions = [residue.position for residue in residues]
    max_position = max(positions) if positions else None
    return ChainCompleteness(
        missing_n_terminal=1 not in positions,
        c_terminal_too_short=max_position is None or max_position < required_c_terminal_position,
        max_position=max_position,
    )
