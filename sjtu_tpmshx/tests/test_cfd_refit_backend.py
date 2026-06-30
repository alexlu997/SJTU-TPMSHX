"""cfd_refit DF backend — K from the clean raw-CFD surface, c_F from gamma_df.

Guards the contract that makes it safe to add as a non-default backend:
  * registered and selectable;
  * c_F is BYTE-IDENTICAL to gamma_df (the Shanghai headline depends on it →
    the Shanghai gate is preserved by construction);
  * K is the CFD-surface value (distinct from gamma_df's Dh²-trend K), in a
    physical range, and reproduces the prebuilt anchors at grid points.
See openspec/changes/df-coeffs-cfd-refit and df_surrogate/cfd_refit.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from df_surrogate.predict import predict_K_cF, available_methods  # noqa: E402


def test_registered():
    assert "cfd_refit" in available_methods()


@pytest.mark.parametrize("tp", ["Diamond", "Gyroid"])
def test_cF_identical_to_gamma_df(tp):
    """c_F must match gamma_df exactly → Shanghai headline unchanged."""
    for L, t in [(7.0, 0.6), (5.0, 0.4), (8.0, 0.3)]:
        _, cF_g = predict_K_cF(tp, L, t, 0.337, method="gamma_df")
        _, cF_r = predict_K_cF(tp, L, t, 0.337, method="cfd_refit")
        assert cF_r == pytest.approx(cF_g, rel=1e-9), f"{tp} {L}/{t}: cF drifted"


@pytest.mark.parametrize("tp", ["Diamond", "Gyroid"])
def test_K_is_cfd_surface(tp):
    """K differs from gamma_df (it's the CFD refit) and stays physical."""
    K_g, _ = predict_K_cF(tp, 7.0, 0.6, 0.337, method="gamma_df")
    K_r, _ = predict_K_cF(tp, 7.0, 0.6, 0.337, method="cfd_refit")
    assert K_r != pytest.approx(K_g, rel=1e-3), "K should be the CFD surface, not gamma_df"
    assert 1e-9 < K_r < 1e-6, f"{tp}: K out of physical range ({K_r:.2e})"


def test_K_reproduces_prebuilt_anchor():
    """At a grid geometry the TPS surface returns ~the tabulated K."""
    import csv
    tbl = _ROOT / "df_surrogate" / "_prebuilt" / "df_cfd_refit_coeffs.csv"
    rows = {(" ".join([r["tp"], r["L"], r["t"]])): float(r["K"])
            for r in csv.DictReader(tbl.open())}
    K_r, _ = predict_K_cF("Gyroid", 7.0, 0.6, 0.337, method="cfd_refit")
    K_tab = rows["Gyroid 7.0 0.6"]
    assert K_r == pytest.approx(K_tab, rel=0.02), "TPS interpolant off its own anchor"
