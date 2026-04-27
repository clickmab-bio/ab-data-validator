from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ab_data_validator.cdr import extract_imgt_cdrs, required_cdr_names
from ab_data_validator.models import AntibodyRow, InputType, ValidationFailure
from ab_data_validator.numbering import NumberedResidue, check_chain_completeness
from ab_data_validator.similarity import calculate_identity, is_high_identity


class PositiveReferenceError(ValueError):
    pass


class Numberer(Protocol):
    def number(self, sequence_id: str, sequence: str, chain: str) -> list[NumberedResidue]:
        pass


class Aligner(Protocol):
    def align(self, cdr_name: str, candidate_cdr: str, positive_cdr: str) -> tuple[str, str]:
        pass


@dataclass(frozen=True)
class ProcessedAntibody:
    row: AntibodyRow
    cdrs: dict[str, str]
    failures: list[ValidationFailure]


@dataclass(frozen=True)
class ProcessedPositive:
    name: str
    input_type: InputType
    cdrs: dict[str, str]


class Validator:
    def __init__(
        self,
        *,
        numberer: Numberer,
        aligner: Aligner,
        identity_threshold: float = 0.8,
    ) -> None:
        self.numberer = numberer
        self.aligner = aligner
        self.identity_threshold = identity_threshold

    def validate(
        self,
        candidates: list[AntibodyRow],
        positives: list[AntibodyRow],
    ) -> list[ValidationFailure]:
        processed_positives = self._process_positives(positives)
        failures: list[ValidationFailure] = []
        for candidate in candidates:
            processed = self._process_candidate(candidate)
            failures.extend(processed.failures)
            failures.extend(self._identity_failures(processed, processed_positives))
        return failures

    def _process_positives(self, positives: list[AntibodyRow]) -> list[ProcessedPositive]:
        processed: list[ProcessedPositive] = []
        for positive in positives:
            item = self._process_antibody(positive, fatal=False)
            if item.failures:
                details = "; ".join(failure.details for failure in item.failures)
                raise PositiveReferenceError(f"positive reference {positive.name} is invalid: {details}")
            processed.append(
                ProcessedPositive(
                    name=positive.name,
                    input_type=positive.input_type,
                    cdrs=item.cdrs,
                )
            )
        return processed

    def _process_candidate(self, candidate: AntibodyRow) -> ProcessedAntibody:
        return self._process_antibody(candidate, fatal=False)

    def _process_antibody(self, row: AntibodyRow, *, fatal: bool) -> ProcessedAntibody:
        del fatal
        cdrs: dict[str, str] = {}
        failures: list[ValidationFailure] = []
        self._process_chain(row, chain="VH", sequence=row.vh, chain_prefix="H", cdrs=cdrs, failures=failures)
        if row.vl is not None:
            self._process_chain(row, chain="VL", sequence=row.vl, chain_prefix="L", cdrs=cdrs, failures=failures)

        for cdr_name in required_cdr_names(row.input_type):
            if cdr_name not in cdrs:
                continue
            if len(cdrs[cdr_name]) < 1:
                chain = "VH" if cdr_name.startswith("CDRH") else "VL"
                failures.append(
                    ValidationFailure(
                        name=row.name,
                        input_type=row.input_type,
                        reason_type="empty_cdr",
                        chain=chain,
                        cdr=cdr_name,
                        details=f"{cdr_name} length is 0",
                    )
                )
        return ProcessedAntibody(row=row, cdrs=cdrs, failures=failures)

    def _process_chain(
        self,
        row: AntibodyRow,
        *,
        chain: str,
        sequence: str,
        chain_prefix: str,
        cdrs: dict[str, str],
        failures: list[ValidationFailure],
    ) -> None:
        try:
            residues = self.numberer.number(row.name, sequence, chain)
        except Exception as error:
            failures.append(
                ValidationFailure(
                    name=row.name,
                    input_type=row.input_type,
                    reason_type="anarci_failed",
                    chain=chain,
                    details=f"{chain} cannot be numbered by ANARCI: {error}",
                )
            )
            return

        completeness = check_chain_completeness(residues)
        if completeness.missing_n_terminal:
            failures.append(
                ValidationFailure(
                    name=row.name,
                    input_type=row.input_type,
                    reason_type="missing_n_terminal",
                    chain=chain,
                    details=f"{chain} IMGT position 1 is absent",
                )
            )
        if completeness.c_terminal_too_short:
            max_position = "none" if completeness.max_position is None else str(completeness.max_position)
            failures.append(
                ValidationFailure(
                    name=row.name,
                    input_type=row.input_type,
                    reason_type="c_terminal_too_short",
                    chain=chain,
                    details=f"{chain} max IMGT position is {max_position}, expected >= 127",
                )
            )
        cdrs.update(extract_imgt_cdrs(residues, chain_prefix=chain_prefix))

    def _identity_failures(
        self,
        candidate: ProcessedAntibody,
        positives: list[ProcessedPositive],
    ) -> list[ValidationFailure]:
        failures: list[ValidationFailure] = []
        for cdr_name in required_cdr_names(candidate.row.input_type):
            candidate_cdr = candidate.cdrs.get(cdr_name)
            if not candidate_cdr:
                continue
            for positive in positives:
                positive_cdr = positive.cdrs.get(cdr_name)
                if not positive_cdr:
                    continue
                aligned_candidate, aligned_positive = self.aligner.align(
                    cdr_name,
                    candidate_cdr,
                    positive_cdr,
                )
                identity = calculate_identity(aligned_candidate, aligned_positive)
                if is_high_identity(identity, threshold=self.identity_threshold):
                    chain = "VH" if cdr_name.startswith("CDRH") else "VL"
                    failures.append(
                        ValidationFailure(
                            name=candidate.row.name,
                            input_type=candidate.row.input_type,
                            reason_type="high_cdr_identity",
                            chain=chain,
                            cdr=cdr_name,
                            positive_name=positive.name,
                            identity=identity,
                            threshold=self.identity_threshold,
                            details=(
                                f"{cdr_name} identity to {positive.name} is "
                                f"{identity:g} >= {self.identity_threshold:g}"
                            ),
                        )
                    )
        return failures
