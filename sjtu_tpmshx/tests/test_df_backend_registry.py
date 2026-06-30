"""B2 2.2 — DF backend registry equivalence + contract guards.

Golden tuples below were captured from the pre-registry dispatch on
2026-06-12 (gamma cF 534.8 == Shanghai gate point; Diamond-7 rbf cF 745
== the falsified extrapolation the D_7_6 gate documents). Any drift here
means the registry refactor changed numbers — it must not.
"""
import numpy as np
import pytest

from df_surrogate import predict as P
from df_surrogate.backend import (DFBackend, available_methods,
                                  get_backend)
from solvers.tpms_calc import geometry as _geom

_EF = {tp: _geom(tp, 7.0, 0.6, 16.0)['epsilon'] / 2
       for tp in ('Gyroid', 'Diamond')}

# (tpms, method) -> (K, cF) at L=7.0, t=0.6, eps_f=_EF — exact values.
_GOLDEN = {
    ('Gyroid', 'gamma_df'): (1.327229597172973e-07, 534.800000000008),
    ('Gyroid', 'rbf'):      (3.218806963975885e-08, 534.7664446055616),
    ('Diamond', 'gamma_df'): (1.6221761754170678e-07, 454.19001394852256),
    ('Diamond', 'rbf'):      (2.4688411110399566e-08, 745.0133131278383),
}


@pytest.mark.parametrize('tpms,method', list(_GOLDEN))
def test_golden_point_values_exact(tpms, method):
    K, cF = P.predict_K_cF(tpms, 7.0, 0.6, _EF[tpms], method=method)
    K_ref, cF_ref = _GOLDEN[(tpms, method)]
    assert K == K_ref
    assert cF == cF_ref


@pytest.mark.parametrize('method', ('gamma_df', 'rbf'))
def test_scalar_vec_parity(method):
    """Vectorised path must agree with the scalar path (modulo the
    scalar-only override layer, empty since 2026-06-11).

    rbf tolerance note: the RBF kernel matmul sums in a different order
    for a 1-row query vs a batched query, giving a last-ulp difference
    between the scalar and vec paths. This is PRE-EXISTING behaviour of
    the retired inline dispatch (verified 2026-06-12), not a registry
    regression — hence rel=1e-12 instead of exact equality here.
    gamma_df is loop-based on both paths → exact.
    """
    L = np.array([5.0, 7.0, 6.0])
    t = np.array([0.4, 0.6, 0.5])
    ef = np.array([_geom('Gyroid', float(l), float(tt), 16.0)['epsilon'] / 2
                   for l, tt in zip(L, t)])
    Kv, cv = P.predict_K_cF_vec('Gyroid', L, t, ef, method=method)
    for i in range(L.size):
        Ks, cs = P.predict_K_cF('Gyroid', float(L[i]), float(t[i]),
                                float(ef[i]), method=method)
        if method == 'gamma_df':
            assert Kv[i] == Ks and cv[i] == cs
        else:
            assert Kv[i] == pytest.approx(Ks, rel=1e-12)
            assert cv[i] == pytest.approx(cs, rel=1e-12)


def test_rbf_clamp_engages_internally():
    """K clamp is RBF-backend-internal: low-permeability geometry floors
    at K_min exactly; gamma_df stays clamp-free at the same point."""
    ef = _geom('Diamond', 4.0, 0.5, 16.0)['epsilon'] / 2
    Kv, _ = P.predict_K_cF_vec('Diamond', np.array([4.0]), np.array([0.5]),
                               np.array([ef]), method='rbf')
    assert Kv[0] == get_backend('Diamond', 'rbf').K_min == 1e-8
    Kg, _ = P.predict_K_cF('Diamond', 4.0, 0.5, ef, method='gamma_df')
    assert Kg != 1e-8


def test_registry_surface():
    # cfd_refit added 2026-06-30 (clean raw-CFD K surface + gamma_df c_F);
    # non-default, see df_surrogate/cfd_refit.py.
    assert set(available_methods()) == {'gamma_df', 'rbf', 'cfd_refit'}
    with pytest.raises(ValueError, match='unknown DF method'):
        P.predict_K_cF('Gyroid', 7.0, 0.6, 0.36, method='plhub_gp_typo')
    b = get_backend('Gyroid', 'gamma_df')
    assert isinstance(b, DFBackend) and b.name == 'gamma_df'
    assert get_backend('Gyroid', 'gamma_df') is b   # cached


def test_diagnostics_passthrough():
    """Unknown attributes reach the wrapped model (existing introspection
    call sites: ._rbf_K, .K_min, .summary)."""
    b = get_backend('Gyroid', 'rbf')
    X = np.array([[7.0, 0.6, _EF['Gyroid']]])
    assert np.isfinite(b._rbf_K(X)[0])     # wrapped-model attribute
    assert b.K_min == 1e-8
    g = get_backend('Gyroid', 'gamma_df')
    assert hasattr(g, 'summary')
