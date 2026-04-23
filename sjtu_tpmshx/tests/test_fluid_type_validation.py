"""Guard: water / sCO2 fluid selections must raise NotImplementedError.

Correlations (Nu, f-Re, D-F surrogate) are fitted for air only. Running
with water or sCO2 silently reuses air's Pr=0.72 and air-fitted closures,
producing unphysical numbers. Validation at solver entry prevents this.
"""
import pytest
from solvers.tpms_calc import (
    parse_fluid_type, validate_fluid_type, _SUPPORTED_FLUIDS,
)


class _FakeCombo:
    def __init__(self, text): self._text = text
    def currentText(self): return self._text


def test_parse_fluid_type_air():
    assert parse_fluid_type(_FakeCombo("Air")) == 'air'


def test_parse_fluid_type_water():
    assert parse_fluid_type(_FakeCombo("Water")) == 'water'


def test_parse_fluid_type_sco2_subscript():
    assert parse_fluid_type(_FakeCombo("sCO₂")) == 'sco2'


def test_parse_fluid_type_sco2_plain():
    assert parse_fluid_type(_FakeCombo("sCO2")) == 'sco2'


def test_validate_air_passes():
    validate_fluid_type('air', 'A')
    validate_fluid_type('air', 'B')


def test_validate_water_raises():
    with pytest.raises(NotImplementedError, match="Water"):
        validate_fluid_type('water', 'A')
    with pytest.raises(NotImplementedError, match="Water"):
        validate_fluid_type('water', 'B')


def test_validate_sco2_raises():
    with pytest.raises(NotImplementedError, match="sCO"):
        validate_fluid_type('sco2', 'A')
    with pytest.raises(NotImplementedError, match="sCO"):
        validate_fluid_type('sco2', 'B')


def test_supported_fluids_locked_to_air():
    assert _SUPPORTED_FLUIDS == {'air'}
