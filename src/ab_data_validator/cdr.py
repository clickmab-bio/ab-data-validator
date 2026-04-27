from __future__ import annotations

from ab_data_validator.models import InputType
from ab_data_validator.numbering import NumberedResidue


IMGT_CDR_RANGES = {
    "1": (27, 38),
    "2": (56, 65),
    "3": (105, 117),
}


def extract_imgt_cdrs(residues: list[NumberedResidue], *, chain_prefix: str) -> dict[str, str]:
    sorted_residues = sorted(residues, key=lambda residue: (residue.position, residue.insertion))
    cdrs: dict[str, str] = {}
    for cdr_number, (start, stop) in IMGT_CDR_RANGES.items():
        cdr_name = f"CDR{chain_prefix}{cdr_number}"
        cdrs[cdr_name] = "".join(
            residue.residue
            for residue in sorted_residues
            if start <= residue.position <= stop and residue.residue not in {"-", "."}
        )
    return cdrs


def required_cdr_names(input_type: InputType) -> list[str]:
    heavy = ["CDRH1", "CDRH2", "CDRH3"]
    if input_type is InputType.NANOBODY:
        return heavy
    return heavy + ["CDRL1", "CDRL2", "CDRL3"]
