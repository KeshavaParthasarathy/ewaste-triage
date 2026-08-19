import pytest

from scripts import valuation


@pytest.fixture
def comp_file(tmp_path):
    p = tmp_path / "composition_priors.csv"
    p.write_text(
        "unu_key,description,frac_pcb,frac_ferrous,frac_nonferrous,frac_plastic,board_grade,source_citation\n"
        "0306,Mobile Phones,0.20,0.05,0.10,0.40,high,TEST\n"
    )
    return p


def test_estimate_uses_measured_mass_when_given(comp_file):
    r = valuation.estimate("0306", mass_g=168.0, composition_path=comp_file)
    assert r["mass_kg"] == pytest.approx(0.168)
    assert r["mass_source"] == "measured"
    assert r["value_usd"] > 0
    assert r["value_low"] < r["value_usd"] < r["value_high"]


def test_estimate_falls_back_to_category_average(comp_file):
    r = valuation.estimate("0306", composition_path=comp_file)
    assert r["mass_kg"] == pytest.approx(0.1)
    assert r["mass_source"] == "UNU EU-28 average"


def test_measured_mass_gives_a_tighter_range(comp_file):
    measured = valuation.estimate("0306", mass_g=168.0, composition_path=comp_file)
    average = valuation.estimate("0306", composition_path=comp_file)
    assert measured["rel_uncertainty"] < average["rel_uncertainty"]


def test_unknown_key_raises(comp_file):
    with pytest.raises(valuation.UnknownKey):
        valuation.estimate("9999", composition_path=comp_file)


def test_missing_composition_file_raises(tmp_path):
    with pytest.raises(valuation.CompositionUnavailable):
        valuation.estimate("0306", composition_path=tmp_path / "nope.csv")
