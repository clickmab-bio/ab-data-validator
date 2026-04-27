import shutil

import pytest

from ab_data_validator.anarci_runner import run_anarci
from ab_data_validator.muscle import align_pair


HEAVY_SEQUENCE = (
    "EVQLQQSGAEVVRSGASVKLSCTASGFNIKDYYIHWVKQRPEKGLEWIGWIDPEIGDTEYVPKFQGK"
    "ATMTADTSSNTAYLQLSSLTSEDTAVYYCNAGHDYDRGRFPYWGQGTLVTVSA"
)
LIGHT_SEQUENCE = (
    "DIQMTQSPSSLSASVGDRVTITCRASQGISSYLNWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSG"
    "TDFTLTISSLQPEDFATYYCQQSYSTPPTFGQGTKVEIK"
)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("ANARCI") is None, reason="ANARCI executable is not installed")
def test_real_anarci_numbers_heavy_and_light_examples():
    heavy = run_anarci(HEAVY_SEQUENCE, sequence_id="heavy")
    light = run_anarci(LIGHT_SEQUENCE, sequence_id="light")

    assert min(residue.position for residue in heavy) == 1
    assert max(residue.position for residue in heavy) >= 127
    assert min(residue.position for residue in light) == 1
    assert max(residue.position for residue in light) >= 127


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("muscle") is None, reason="MUSCLE executable is not installed")
def test_real_muscle_aligns_two_cdr_sequences():
    aligned_a, aligned_b = align_pair("ARDY", "ARDYG")

    assert len(aligned_a) == len(aligned_b)
    assert aligned_a.replace("-", "") == "ARDY"
    assert aligned_b.replace("-", "") == "ARDYG"
