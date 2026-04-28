from ab_data_validator.cdr import extract_imgt_cdrs, required_cdr_names
from ab_data_validator.models import InputType
from ab_data_validator.numbering import NumberedResidue, check_chain_completeness


def make_chain(start, stop, residue="A"):
    return [NumberedResidue(position=position, insertion="", residue=residue) for position in range(start, stop + 1)]


def test_chain_requires_imgt_position_one():
    chain = make_chain(2, 127)

    result = check_chain_completeness(chain)

    assert not result.is_complete
    assert result.missing_n_terminal


def test_chain_accepts_max_position_127():
    chain = make_chain(1, 127)

    result = check_chain_completeness(chain)

    assert result.is_complete
    assert result.max_position == 127


def test_chain_rejects_max_position_below_127():
    chain = make_chain(1, 126)

    result = check_chain_completeness(chain)

    assert not result.is_complete
    assert result.c_terminal_too_short
    assert result.max_position == 126


def test_chain_rejects_max_position_below_explicit_requirement():
    chain = make_chain(1, 127)

    result = check_chain_completeness(chain, required_c_terminal_position=128)

    assert not result.is_complete
    assert result.c_terminal_too_short
    assert result.max_position == 127


def test_extracts_imgt_heavy_chain_cdrs():
    chain = make_chain(1, 127)

    cdrs = extract_imgt_cdrs(chain, chain_prefix="H")

    assert cdrs["CDRH1"] == "A" * 12
    assert cdrs["CDRH2"] == "A" * 10
    assert cdrs["CDRH3"] == "A" * 13


def test_extract_imgt_cdrs_excludes_anarci_gap_residues():
    chain = make_chain(1, 127)
    chain[26] = NumberedResidue(position=27, insertion="", residue="-")
    chain[27] = NumberedResidue(position=28, insertion="", residue="G")

    cdrs = extract_imgt_cdrs(chain, chain_prefix="H")

    assert cdrs["CDRH1"] == "G" + "A" * 10


def test_extracts_imgt_light_chain_cdrs():
    chain = make_chain(1, 127, residue="S")

    cdrs = extract_imgt_cdrs(chain, chain_prefix="L")

    assert cdrs["CDRL1"] == "S" * 12
    assert cdrs["CDRL2"] == "S" * 10
    assert cdrs["CDRL3"] == "S" * 13


def test_missing_cdr_region_extracts_empty_sequence():
    chain = make_chain(1, 26) + make_chain(39, 127)

    cdrs = extract_imgt_cdrs(chain, chain_prefix="H")

    assert cdrs["CDRH1"] == ""


def test_required_cdr_names_depend_on_input_type():
    assert required_cdr_names(InputType.NANOBODY) == ["CDRH1", "CDRH2", "CDRH3"]
    assert required_cdr_names(InputType.FULL_ANTIBODY) == [
        "CDRH1",
        "CDRH2",
        "CDRH3",
        "CDRL1",
        "CDRL2",
        "CDRL3",
    ]
