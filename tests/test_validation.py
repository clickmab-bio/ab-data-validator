import time

import pytest

from ab_data_validator.muscle import MuscleError
from ab_data_validator.models import AntibodyRow
from ab_data_validator.numbering import NumberedResidue
from ab_data_validator.validation import PositiveReferenceError, Validator


def make_chain(h1="A", h2="B", h3="C", *, stop=128):
    residues = [NumberedResidue(position=position, insertion="", residue="F") for position in range(1, stop + 1)]
    replacements = {
        range(27, 39): h1,
        range(56, 66): h2,
        range(105, 118): h3,
    }
    return [
        NumberedResidue(
            position=residue.position,
            insertion=residue.insertion,
            residue=next((value for positions, value in replacements.items() if residue.position in positions), residue.residue),
        )
        for residue in residues
    ]


class FakeNumberer:
    def __init__(self, mapping):
        self.mapping = mapping

    def number(self, sequence_id, sequence, chain):
        result = self.mapping[sequence]
        if isinstance(result, Exception):
            raise result
        return result


class RecordingAligner:
    def __init__(self, high_identity_pairs=None):
        self.calls = []
        self.high_identity_pairs = high_identity_pairs or set()

    def align(self, cdr_name, candidate_cdr, positive_cdr):
        self.calls.append((cdr_name, candidate_cdr, positive_cdr))
        if cdr_name in self.high_identity_pairs:
            return candidate_cdr, candidate_cdr
        return candidate_cdr, "X" * len(candidate_cdr)


def test_nanobody_validates_only_heavy_chain_and_heavy_cdrs():
    candidate = AntibodyRow(name="Nb1", vh="nb_h", vl=None)
    positive = AntibodyRow(name="Pos1", vh="pos_h", vl="pos_l")
    aligner = RecordingAligner()
    validator = Validator(
        numberer=FakeNumberer(
            {
                "nb_h": make_chain("A", "B", "C"),
                "pos_h": make_chain("D", "E", "F"),
                "pos_l": make_chain("G", "H", "I"),
            }
        ),
        aligner=aligner,
    )

    failures = validator.validate([candidate], [positive])

    assert failures == []
    assert [call[0] for call in aligner.calls] == ["CDRH1", "CDRH2", "CDRH3"]


def test_full_antibody_high_identity_failure_is_recorded():
    candidate = AntibodyRow(name="Ab1", vh="ab_h", vl="ab_l")
    positive = AntibodyRow(name="Pos1", vh="pos_h", vl="pos_l")
    validator = Validator(
        numberer=FakeNumberer(
            {
                "ab_h": make_chain("A", "B", "C"),
                "ab_l": make_chain("D", "E", "F"),
                "pos_h": make_chain("G", "H", "I"),
                "pos_l": make_chain("J", "K", "L"),
            }
        ),
        aligner=RecordingAligner(high_identity_pairs={"CDRH3"}),
    )

    failures = validator.validate([candidate], [positive])

    assert len(failures) == 1
    assert failures[0].reason_type == "high_cdr_identity"
    assert failures[0].cdr == "CDRH3"
    assert failures[0].positive_name == "Pos1"
    assert failures[0].identity == 1.0
    assert failures[0].threshold == 0.8


def test_candidate_records_multiple_chain_and_cdr_failures():
    candidate = AntibodyRow(name="BadNb", vh="bad_h", vl=None)
    positive = AntibodyRow(name="Pos1", vh="pos_h", vl=None)
    bad_chain = make_chain()[1:26] + make_chain()[38:126]
    validator = Validator(
        numberer=FakeNumberer({"bad_h": bad_chain, "pos_h": make_chain("D", "E", "F")}),
        aligner=RecordingAligner(),
    )

    failures = validator.validate([candidate], [positive])

    assert [failure.reason_type for failure in failures] == [
        "missing_n_terminal",
        "c_terminal_too_short",
        "empty_cdr",
    ]
    assert failures[2].cdr == "CDRH1"


def test_candidate_with_chain_failure_still_reports_available_high_identity_cdrs():
    candidate = AntibodyRow(name="ShortNb", vh="short_h", vl=None)
    positive = AntibodyRow(name="Pos1", vh="pos_h", vl=None)
    short_chain_with_cdrs = make_chain()[:126]
    validator = Validator(
        numberer=FakeNumberer({"short_h": short_chain_with_cdrs, "pos_h": make_chain("D", "E", "F")}),
        aligner=RecordingAligner(high_identity_pairs={"CDRH3"}),
    )

    failures = validator.validate([candidate], [positive])

    assert [failure.reason_type for failure in failures] == [
        "c_terminal_too_short",
        "high_cdr_identity",
    ]
    assert failures[1].cdr == "CDRH3"


def test_heavy_chain_requires_imgt_position_128():
    candidate = AntibodyRow(name="ShortHeavy", vh="short_h", vl=None)
    positive = AntibodyRow(name="Pos1", vh="pos_h", vl=None)
    validator = Validator(
        numberer=FakeNumberer({"short_h": make_chain(stop=127), "pos_h": make_chain("D", "E", "F")}),
        aligner=RecordingAligner(),
    )

    failures = validator.validate([candidate], [positive])

    assert [failure.reason_type for failure in failures] == ["c_terminal_too_short"]
    assert failures[0].chain == "VH"
    assert failures[0].details == "VH max IMGT position is 127, expected >= 128"


def test_light_chain_accepts_imgt_position_127():
    candidate = AntibodyRow(name="FullAb", vh="ab_h", vl="ab_l")
    positive = AntibodyRow(name="Pos1", vh="pos_h", vl="pos_l")
    validator = Validator(
        numberer=FakeNumberer(
            {
                "ab_h": make_chain("A", "B", "C"),
                "ab_l": make_chain("D", "E", "F", stop=127),
                "pos_h": make_chain("G", "H", "I"),
                "pos_l": make_chain("J", "K", "L", stop=127),
            }
        ),
        aligner=RecordingAligner(),
    )

    failures = validator.validate([candidate], [positive])

    assert failures == []


def test_invalid_positive_reference_is_fatal():
    candidate = AntibodyRow(name="Nb1", vh="nb_h", vl=None)
    positive = AntibodyRow(name="BadPos", vh="bad_pos_h", vl=None)
    validator = Validator(
        numberer=FakeNumberer({"nb_h": make_chain(), "bad_pos_h": make_chain()[1:]}),
        aligner=RecordingAligner(),
    )

    with pytest.raises(PositiveReferenceError, match="BadPos"):
        validator.validate([candidate], [positive])


def test_positive_nanobody_skips_light_chain_comparisons_for_full_candidate():
    candidate = AntibodyRow(name="Ab1", vh="ab_h", vl="ab_l")
    positive = AntibodyRow(name="PosNb", vh="pos_h", vl=None)
    aligner = RecordingAligner()
    validator = Validator(
        numberer=FakeNumberer(
            {
                "ab_h": make_chain("A", "B", "C"),
                "ab_l": make_chain("D", "E", "F"),
                "pos_h": make_chain("G", "H", "I"),
            }
        ),
        aligner=aligner,
    )

    validator.validate([candidate], [positive])

    assert [call[0] for call in aligner.calls] == ["CDRH1", "CDRH2", "CDRH3"]


def test_progress_logger_records_major_validation_stages_in_order():
    messages = []
    validator = Validator(
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain("D", "E", "F")}),
        aligner=RecordingAligner(),
        progress_logger=messages.append,
    )

    validator.validate(
        [AntibodyRow(name="Ab1", vh="ab_h", vl=None)],
        [AntibodyRow(name="Pos1", vh="pos_h", vl=None)],
    )

    assert messages == [
        "Numbering positive references",
        "Numbered 1 positive references",
        "Numbering candidate antibodies",
        "Numbered 1 candidate antibodies",
        "Comparing candidate CDRs to positive references",
        "Completed CDR identity comparisons",
    ]


def test_parallel_candidate_processing_preserves_input_order():
    class DelayingNumberer(FakeNumberer):
        def number(self, sequence_id, sequence, chain):
            if sequence == "first_bad":
                time.sleep(0.02)
            return super().number(sequence_id, sequence, chain)

    bad_chain = make_chain()[1:]
    validator = Validator(
        numberer=DelayingNumberer(
            {
                "first_bad": bad_chain,
                "second_bad": bad_chain,
                "pos_h": make_chain("D", "E", "F"),
            }
        ),
        aligner=RecordingAligner(),
        max_workers=2,
    )

    failures = validator.validate(
        [
            AntibodyRow(name="First", vh="first_bad", vl=None),
            AntibodyRow(name="Second", vh="second_bad", vl=None),
        ],
        [AntibodyRow(name="Pos1", vh="pos_h", vl=None)],
    )

    assert [failure.name for failure in failures] == ["First", "Second"]


def test_parallel_identity_processing_preserves_cdr_and_positive_order():
    class AlwaysHighIdentityAligner:
        def align(self, cdr_name, candidate_cdr, positive_cdr):
            if cdr_name == "CDRH1" and positive_cdr.startswith("D"):
                time.sleep(0.02)
            return candidate_cdr, candidate_cdr

    validator = Validator(
        numberer=FakeNumberer(
            {
                "ab_h": make_chain("A", "B", "C"),
                "pos1_h": make_chain("D", "E", "F"),
                "pos2_h": make_chain("G", "H", "I"),
            }
        ),
        aligner=AlwaysHighIdentityAligner(),
        max_workers=4,
    )

    failures = validator.validate(
        [AntibodyRow(name="Ab1", vh="ab_h", vl=None)],
        [
            AntibodyRow(name="Pos1", vh="pos1_h", vl=None),
            AntibodyRow(name="Pos2", vh="pos2_h", vl=None),
        ],
    )

    assert [(failure.cdr, failure.positive_name) for failure in failures] == [
        ("CDRH1", "Pos1"),
        ("CDRH1", "Pos2"),
        ("CDRH2", "Pos1"),
        ("CDRH2", "Pos2"),
        ("CDRH3", "Pos1"),
        ("CDRH3", "Pos2"),
    ]


def test_parallel_positive_processing_reports_first_invalid_positive_in_input_order():
    class DelayingNumberer(FakeNumberer):
        def number(self, sequence_id, sequence, chain):
            if sequence == "bad_first":
                time.sleep(0.02)
            return super().number(sequence_id, sequence, chain)

    bad_chain = make_chain()[1:]
    validator = Validator(
        numberer=DelayingNumberer(
            {
                "bad_first": bad_chain,
                "bad_second": bad_chain,
            }
        ),
        aligner=RecordingAligner(),
        max_workers=2,
    )

    with pytest.raises(PositiveReferenceError, match="BadFirst"):
        validator.validate(
            [AntibodyRow(name="Ab1", vh="unused", vl=None)],
            [
                AntibodyRow(name="BadFirst", vh="bad_first", vl=None),
                AntibodyRow(name="BadSecond", vh="bad_second", vl=None),
            ],
        )


def test_parallel_identity_processing_propagates_alignment_errors():
    class FailingAligner:
        def align(self, cdr_name, candidate_cdr, positive_cdr):
            raise MuscleError("MUSCLE failed")

    validator = Validator(
        numberer=FakeNumberer({"ab_h": make_chain(), "pos_h": make_chain()}),
        aligner=FailingAligner(),
        max_workers=2,
    )

    with pytest.raises(MuscleError, match="MUSCLE failed"):
        validator.validate(
            [AntibodyRow(name="Ab1", vh="ab_h", vl=None)],
            [AntibodyRow(name="Pos1", vh="pos_h", vl=None)],
        )
