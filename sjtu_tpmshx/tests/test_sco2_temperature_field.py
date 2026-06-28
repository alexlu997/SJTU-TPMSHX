"""Vectorised T(h,P) inverse for the Option B enthalpy-form 3D LTNE rewrite.

The conservative enthalpy kernel keeps h as the primary fluid unknown; the
pipeline (stages_3d) must invert T = T(h,P) each outer iteration to feed the
diffusion/inter-phase coupling. sco2_temperature_field is the field counterpart
of the scalar sco2_temperature (the per-cell array form the kernel refresh needs).
"""
import numpy as np
import pytest

from solvers import sco2_props

pytestmark = pytest.mark.skipif(
    not sco2_props._HAVE_COOLPROP, reason="CoolProp required for sCO2 tests")

_P = 8.0e6


def test_temperature_field_round_trips_enthalpy_field():
    """T(h(T)) == T over a field spanning the pseudocritical line."""
    T = np.array([[290.0, 307.0], [312.0, 360.0]])
    h = sco2_props.sco2_enthalpy_field(T, _P)
    T_back = sco2_props.sco2_temperature_field(h, _P)
    assert T_back.shape == T.shape
    assert np.allclose(T_back, T, atol=1e-3)


def test_temperature_field_matches_scalar():
    """Field query agrees with the scalar sco2_temperature element-wise."""
    h = np.array([sco2_props.sco2_enthalpy(300.0, _P),
                  sco2_props.sco2_enthalpy(330.0, _P)])
    Tf = sco2_props.sco2_temperature_field(h, _P)
    assert Tf[0] == pytest.approx(sco2_props.sco2_temperature(float(h[0]), _P), rel=1e-9)
    assert Tf[1] == pytest.approx(sco2_props.sco2_temperature(float(h[1]), _P), rel=1e-9)
