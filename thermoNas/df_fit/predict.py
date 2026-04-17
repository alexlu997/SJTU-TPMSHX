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
    >>> from thermoNas.df_fit.predict import predict_K_cF, predict_dP_compressible
    >>> K, cF = predict_K_cF('Gyroid', 7.0, 0.6, 0.368)
    >>> dP = predict_dP_compressible('Gyroid', 7.0, 0.6, 0.368,
    ...          G=63.05, T=370.7, P_in=304746, mu=2.16e-5, L=0.231)
"""
from __future__ import annotations

import sys
from math import sqrt
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

R_AIR = 287.05


# ==================================================================
# Backend: SurrogateV3
# ==================================================================

_CACHE: dict[str, object] = {}


def _get_model(tpms_type: str):
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
    """Vectorised variant for solver iteration over grid cells."""
    model = _get_model(tpms_type)
    K_out = np.empty(len(L_mm))
    cF_out = np.empty(len(L_mm))
    for i in range(len(L_mm)):
        K_out[i], cF_out[i] = model.predict(
            float(L_mm[i]), float(t_mm[i]), float(eps_f[i]))
    return K_out, cF_out


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
                            L: float) -> float:
    """1D compressible isothermal D-F pressure drop.

    P_out^2 = P_in^2 - 2*R*T*(mu*G/K + c_F*G^2)*L

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
        return P_in
    return P_in - sqrt(P_out_sq)


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
