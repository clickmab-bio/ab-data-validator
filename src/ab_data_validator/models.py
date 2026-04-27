from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InputType(Enum):
    FULL_ANTIBODY = "full_antibody"
    NANOBODY = "nanobody"


@dataclass(frozen=True)
class AntibodyRow:
    name: str
    vh: str
    vl: str | None

    @property
    def input_type(self) -> InputType:
        if self.vl is None:
            return InputType.NANOBODY
        return InputType.FULL_ANTIBODY


@dataclass(frozen=True)
class ValidationFailure:
    name: str
    input_type: InputType
    reason_type: str
    details: str
    chain: str = ""
    cdr: str = ""
    positive_name: str = ""
    identity: float | None = None
    threshold: float | None = None
