from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol, TypeVar

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


@dataclass(frozen=True)
class IdentityComparison:
    candidate_name: str
    candidate_input_type: InputType
    cdr_name: str
    candidate_cdr: str
    positive_name: str
    positive_cdr: str


InputItem = TypeVar("InputItem")
OutputItem = TypeVar("OutputItem")
ProgressLogger = Callable[[str], None]


CHAIN_REQUIRED_C_TERMINAL_POSITIONS = {
    "VH": 128,
    "VL": 127,
}


class Validator:
    def __init__(
        self,
        *,
        numberer: Numberer,
        aligner: Aligner,
        identity_threshold: float = 0.8,
        max_workers: int = 1,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be greater than or equal to 1")
        self.numberer = numberer
        self.aligner = aligner
        self.identity_threshold = identity_threshold
        self.max_workers = max_workers
        self.progress_logger = progress_logger

    def validate(
        self,
        candidates: list[AntibodyRow],
        positives: list[AntibodyRow],
    ) -> list[ValidationFailure]:
        self._log_progress("Numbering positive references")
        processed_positives = self._process_positives(positives)
        self._log_progress(f"Numbered {len(processed_positives)} positive references")

        self._log_progress("Numbering candidate antibodies")
        processed_candidates = self._ordered_map(self._process_candidate, candidates)
        self._log_progress(f"Numbered {len(processed_candidates)} candidate antibodies")

        self._log_progress("Comparing candidate CDRs to positive references")
        failures: list[ValidationFailure] = []
        for processed in processed_candidates:
            failures.extend(processed.failures)
            failures.extend(self._identity_failures(processed, processed_positives))
        self._log_progress("Completed CDR identity comparisons")
        return failures

    def _log_progress(self, message: str) -> None:
        if self.progress_logger is not None:
            self.progress_logger(message)

    def _process_positives(self, positives: list[AntibodyRow]) -> list[ProcessedPositive]:
        processed: list[ProcessedPositive] = []
        processed_items = self._ordered_map(lambda positive: self._process_antibody(positive, fatal=False), positives)
        for positive, item in zip(positives, processed_items, strict=True):
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

        required_c_terminal_position = CHAIN_REQUIRED_C_TERMINAL_POSITIONS[chain]
        completeness = check_chain_completeness(
            residues,
            required_c_terminal_position=required_c_terminal_position,
        )
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
                    details=(
                        f"{chain} max IMGT position is {max_position}, "
                        f"expected >= {required_c_terminal_position}"
                    ),
                )
            )
        cdrs.update(extract_imgt_cdrs(residues, chain_prefix=chain_prefix))

    def _identity_failures(
        self,
        candidate: ProcessedAntibody,
        positives: list[ProcessedPositive],
    ) -> list[ValidationFailure]:
        comparisons: list[IdentityComparison] = []
        for cdr_name in required_cdr_names(candidate.row.input_type):
            candidate_cdr = candidate.cdrs.get(cdr_name)
            if not candidate_cdr:
                continue
            for positive in positives:
                positive_cdr = positive.cdrs.get(cdr_name)
                if not positive_cdr:
                    continue
                comparisons.append(
                    IdentityComparison(
                        candidate_name=candidate.row.name,
                        candidate_input_type=candidate.row.input_type,
                        cdr_name=cdr_name,
                        candidate_cdr=candidate_cdr,
                        positive_name=positive.name,
                        positive_cdr=positive_cdr,
                    )
                )
        failures = self._ordered_map(self._identity_failure, comparisons)
        return [failure for failure in failures if failure is not None]

    def _identity_failure(self, comparison: IdentityComparison) -> ValidationFailure | None:
        aligned_candidate, aligned_positive = self.aligner.align(
            comparison.cdr_name,
            comparison.candidate_cdr,
            comparison.positive_cdr,
        )
        identity = calculate_identity(aligned_candidate, aligned_positive)
        if not is_high_identity(identity, threshold=self.identity_threshold):
            return None
        chain = "VH" if comparison.cdr_name.startswith("CDRH") else "VL"
        return ValidationFailure(
            name=comparison.candidate_name,
            input_type=comparison.candidate_input_type,
            reason_type="high_cdr_identity",
            chain=chain,
            cdr=comparison.cdr_name,
            positive_name=comparison.positive_name,
            identity=identity,
            threshold=self.identity_threshold,
            details=(
                f"{comparison.cdr_name} identity to {comparison.positive_name} is "
                f"{identity:g} >= {self.identity_threshold:g}"
            ),
        )

    def _ordered_map(
        self,
        function: Callable[[InputItem], OutputItem],
        items: Sequence[InputItem],
    ) -> list[OutputItem]:
        if self.max_workers <= 1 or len(items) <= 1:
            return [function(item) for item in items]
        workers = min(self.max_workers, len(items))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(function, items))
