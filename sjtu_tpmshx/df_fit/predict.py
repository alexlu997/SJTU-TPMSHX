"""
Step 5: runtime inference for Darcy-Forchheimer coefficients.

Interface
---------
    predict_K_cF(tpms_type, L_mm, t_mm, eps_f) -> (K, c_F)
    predict_K_cF_vec(tpms_type, L_mm_arr, t_mm_arr, eps_f_arr)
                                                 -> (K_arr, c_F_arr)
    predict_dP(tpms_type, L_mm, t_mm, eps_f, u, rho, mu, L_channel_m)
                                                 -> dP [Pa]
    predict_dP_compressible(tpms_type, L_mm, t_mm, eps_f, G, T, P_in, mu, L)
                                                 -> dP [Pa]

Backend: SurrogateV3 — RBF interpolation with compressible calibration
and boundary effect correction. See surrogate_v3.py for details.

Usage
-----
    >>> from sjtu_tpmshx.df_fit.predict import predict_K_cF, predict_dP_compressible
    >>> K, cF = predict_K_cF('Gyroid', 7.0, 0.6, 0.368)
    >>> dP = predict_dP_compressible('Gyroid', 7.0, 0.6, 0.368,
    ...          G=63.05, T=370.7, P_in=304746, mu=2.16e-5, L=0.231)
"""
from __future__ import annotations

import os
import sys
from math import sqrt
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

R_AIR = 287.05


def _residual_correction_enabled() -> bool:
    """Env-var-gated toggle for residual learning correction.

    Set TPMSHX_DF_RESIDUAL_CORR=1 to enable. Default off — preserves
    historical baseline behavior in tests, optimizers, and existing scripts.
    """
    return os.environ.get("TPMSHX_DF_RESIDUAL_CORR", "0").strip() == "1"


# ==================================================================
# Backend: SurrogateV3
# ==================================================================

_CACHE: dict[str, "object"] = {}


def _get_model(tpms_type: str) -> "object":
    """Return cached SurrogateV3 instance for tpms_type. Lazy-loaded."""
    if tpms_type not in _CACHE:
        from .surrogate_v3 import SurrogateV3
        _CACHE[tpms_type] = SurrogateV3(tpms=tpms_type)
    return _CACHE[tpms_type]


# ==================================================================
# Public API
# ==================================================================

def predict_K_cF(tpms_type: str, L_mm: float, t_mm: float,
                 eps_f: float) -> tuple[float, float]:
    """Return (K [m^2], c_F [1/m]) for this geometry."""
    return _get_model(tpms_type).predict(L_mm, t_mm, eps_f)


def predict_K_cF_vec(tpms_type: str, L_mm: np.ndarray, t_mm: np.ndarray,
                     eps_f: np.ndarray
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised variant for solver iteration over grid cells.

    Shape-agnostic: accepts any compatible array shape (1D, 2D, 3D). The
    returned (K, c_F) arrays match the input shape. Inputs are broadcast
    together.
    """
    model = _get_model(tpms_type)
    L_arr = np.asarray(L_mm, dtype=np.float64)
    t_arr = np.asarray(t_mm, dtype=np.float64)
    e_arr = np.asarray(eps_f, dtype=np.float64)
    shape = np.broadcast(L_arr, t_arr, e_arr).shape
    Lf = np.broadcast_to(L_arr, shape).ravel()
    tf = np.broadcast_to(t_arr, shape).ravel()
    ef = np.broadcast_to(e_arr, shape).ravel()
    n = Lf.size
    K_out = np.empty(n, dtype=np.float64)
    cF_out = np.empty(n, dtype=np.float64)
    for i in range(n):
        K_out[i], cF_out[i] = model.predict(float(Lf[i]), float(tf[i]), float(ef[i]))
    return K_out.reshape(shape), cF_out.reshape(shape)


def predict_dP(tpms_type: str, L_mm: float, t_mm: float, eps_f: float,
               u: float, rho: float, mu: float,
               L_channel_m: float) -> float:
    """Compute dP via incompressible D-F (backward-compatible interface).

    For compressible flow, use predict_dP_compressible instead.
    """
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f)
    return (mu * u / K + rho * c_F * u ** 2) * L_channel_m


def predict_dP_compressible(tpms_type: str, L_mm: float, t_mm: float,
                            eps_f: float, G: float, T: float,
                            P_in: float, mu: float,
                            L: float, strict: bool = False) -> float:
    """1D compressible isothermal D-F pressure drop.

    P_out^2 = P_in^2 - 2*R*T*(mu*G/K + c_F*G^2)*L

    If env var ``TPMSHX_DF_RESIDUAL_CORR=1`` is set, applies the residual
    learning correction: dP_corrected = dP_baseline * (1 + g(Re, eps_f)).
    See `residual_correction.py` for details.

    Parameters
    ----------
    G : mass flux [kg/(m^2 s)]
    T : temperature [K]
    P_in : inlet absolute pressure [Pa]
    mu : dynamic viscosity [Pa s]
    L : channel length [m]
    """
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f)
    C = mu * G / K + c_F * G ** 2
    P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L
    if P_out_sq <= 0:
        # Codex #6: infeasible (no real P_out). strict → NaN for
        # detect+exclude+count; default → legacy P_in (optimizer untouched).
        return float('nan') if strict else P_in
    dP_baseline = P_in - sqrt(P_out_sq)

    if not _residual_correction_enabled():
        return dP_baseline

    # Apply residual learning correction
    from .residual_correction import get_corrector
    from solvers.tpms_calc import geometry as tpms_geometry
    geom = tpms_geometry(tpms_type, L_mm, t_mm, 16.0)
    D_h = float(geom["D_h"])
    rho_in = P_in / (R_AIR * T)
    u_in = G / rho_in
    Re = rho_in * u_in * D_h / mu
    g = get_corrector(tpms_type).correction(Re, eps_f)
    return max(dP_baseline * (1.0 + g), 0.0)


# ==================================================================
# Smoke test
# ==================================================================

def smoke_test() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    model = _get_model("Gyroid")
    model.summary()

    # Quick Shanghai check
    from solvers.tpms_calc import geometry as tpms_geometry
    g = tpms_geometry("Gyroid", 7.0, 0.6, 16.0)
    K, cF = predict_K_cF("Gyroid", 7.0, 0.6, g["epsilon"] / 2)
    print(f"\nL=7 t=0.6: K={K:.4e}, c_F={cF:.2f}")
    print(f"(optimal: K=inf, c_F=372.7)")


if __name__ == "__main__":
    smoke_test()
