"""minmod (solvers/_kernels_2d) must stay byte-identical to the inline block
the SOU deferred-correction kernels used before extraction (DUP-C / #4)."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers._kernels_2d import minmod


def _minmod_ref(gu, gd):
    """The exact block minmod() replaced in every _sou_corr_* kernel."""
    phi = 0.0
    if gu * gd > 0:
        phi = min(abs(gu), abs(gd))
        if gu < 0:
            phi = -phi
    return phi


@pytest.mark.parametrize("gu,gd", [
    (0.0, 0.0), (1.0, 0.0), (0.0, 1.0),
    (2.0, 3.0), (3.0, 2.0), (-2.0, -3.0), (-3.0, -2.0),
    (1.0, -1.0), (-1.0, 1.0), (1e-12, 1e-12), (5.0, -0.1),
    (-0.1, -5.0), (1.5, 1.5),
])
def test_minmod_matches_reference_scalar(gu, gd):
    assert minmod(gu, gd) == _minmod_ref(gu, gd)


def test_minmod_matches_reference_random():
    rng = np.random.default_rng(7)
    a = rng.standard_normal(5000)
    b = rng.standard_normal(5000)
    for gu, gd in zip(a, b):
        assert minmod(float(gu), float(gd)) == _minmod_ref(float(gu), float(gd))


def test_minmod_properties():
    assert minmod(2.0, 5.0) == 2.0      # same sign -> signed min magnitude
    assert minmod(-2.0, -5.0) == -2.0
    assert minmod(2.0, -5.0) == 0.0     # opposite sign -> 0
    assert minmod(0.0, 5.0) == 0.0      # zero -> 0
