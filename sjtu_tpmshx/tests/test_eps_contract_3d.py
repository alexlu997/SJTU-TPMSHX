"""ε contract guard — Option A: caller passes FULL porosity, kernel halves once.

Bug (pre-2026-05-19): callers passed 0.5*eps (pre-halved ε_A) AND the kernel
`solve_full_domain_3d` internally does `eps_f = 0.5*epsilon` → ε double-halved
to ε_full/4, halving LTNE fluid convective heat capacity.

Option A fix: kernel keeps its single internal halving; every production
caller must pass the FULL porosity ε_full (≈0.7368 for Shanghai Gyroid),
NOT the pre-halved ε_A (≈0.368).

These tests pin the contract end-to-end so a caller can never silently
re-introduce the pre-halving.
"""
import numpy as np
import pandas as pd
import pytest


def _shanghai_df():
    import validation.cases.validate_shanghai_3d_real as V
    p = V._ROOT.parent / "data" / "raw_data" / \
        "20260401-上海电气天然气加热器实验工况.xlsx" \
        if hasattr(V, "_ROOT") else None
    # validate module uses ROOT (parents[1]); data at ROOT.parent/data
    import pathlib
    root = pathlib.Path(V.__file__).resolve().parents[1]
    xlsx = root.parent / "data" / "raw_data" / \
        "20260401-上海电气天然气加热器实验工况.xlsx"
    return pd.read_excel(str(xlsx), engine="openpyxl",
                         sheet_name="Sheet1", header=None, skiprows=2)


def test_validate_shanghai_passes_full_epsilon(monkeypatch):
    """validate_shanghai_3d_real must hand the kernel FULL ε, not ε_A."""
    import validation.cases.validate_shanghai_3d_real as V

    captured = {}

    def spy(*a, **kw):
        # kernel signature positional order:
        # 0L 1H 2D 3Nx 4Ny 5Nz 6T_inA 7T_inB 8K_ffA 9K_ffB 10K_ss
        # 11h_vA 12h_vB 13rho_cp_fA 14rho_cp_fB 15epsilon ...
        eps = a[15] if len(a) > 15 else kw.get("epsilon")
        captured["eps"] = float(np.asarray(eps, dtype=float).max())
        Nx, Ny, Nz = a[3], a[4], a[5]
        z = np.full((Nx, Ny, Nz), 300.0, dtype=np.float64)
        return z, z.copy(), z.copy()

    monkeypatch.setattr(V, "solve_full_domain_3d", spy)
    monkeypatch.setattr(V.SIMPLESolver3D, "solve",
                        lambda self, *a, **k: None)

    df = _shanghai_df()
    V._run_one_case(0, df, 4, 4, 2, max_outer=1)

    assert "eps" in captured, "kernel was never called"
    # Shanghai Gyroid L=7,t=0.6 full porosity ≈ 0.7368; ε_A ≈ 0.3684.
    assert captured["eps"] == pytest.approx(V.EPS, rel=1e-3), (
        f"caller passed epsilon.max()={captured['eps']:.4f}; "
        f"expected FULL ε={V.EPS:.4f} (Option A: kernel halves once). "
        f"Pre-halved value (~{V.EPS/2:.4f}) means the ε double-halving "
        f"regression is back."
    )
