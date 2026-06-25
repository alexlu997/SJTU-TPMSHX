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

Backends (selectable per call via ``method=`` or globally via env
``TPMSHX_DF_METHOD``):

    "gamma_df" (default since 2026-06-12)
                     GammaDF — multi-fidelity smooth-CFD-surface x
                     experimental roughness factor.  Trusted-anchor LOO
                     2.5%/2.6%; D7 blind 454.2 vs ~454.  Gate-point cF
                     identical to the RBF (534.8); K is the SMOOTH D_h^2
                     trend — Shanghai 3D Nz=3: dP 9.82% / Q 3.20%.
                     See gamma_df.py.
    "rbf"            SurrogateV3 — RBF interpolation with compressible
                     calibration and boundary effect correction; the
                     pre-2026-06-12 production default (Shanghai 3D Nz=3
                     dP 7.19% / Q 3.22%, but D7-class extrapolation
                     falsified: 745 vs ~454, end-to-end 67.4%).
                     Restore globally with TPMSHX_DF_METHOD=rbf.
                     See surrogate_v3.py.

Usage
-----
    >>> from sjtu_tpmshx.df_surrogate.predict import predict_K_cF, predict_dP_compressible
    >>> K, cF = predict_K_cF('Gyroid', 7.0, 0.6, 0.368)
    >>> dP = predict_dP_compressible('Gyroid', 7.0, 0.6, 0.368,
    ...          G=63.05, T=370.7, P_in=304746, mu=2.16e-5, L=0.231)
"""
from __future__ import annotations

import os
import sys
import warnings
from math import sqrt
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent

R_AIR = 287.05

# One-shot warning when the 1D compressible dP is infeasible (choked) and the
# non-strict path rescues to P_in (robustness 2026-06-25).
_CHOKE_WARNED: set = set()


def _residual_correction_enabled() -> bool:
    """Env-var-gated toggle for residual learning correction.

    Set TPMSHX_DF_RESIDUAL_CORR=1 to enable. Default off — preserves
    historical baseline behavior in tests, optimizers, and existing scripts.
    """
    return os.environ.get("TPMSHX_DF_RESIDUAL_CORR", "0").strip() == "1"


# ==================================================================
# End-to-end calibrated overrides (2026-06-11)
# ==================================================================
# Specimen experiments (26-cell flow / 36-cell frontal, total-dP) bridged
# into the production surface via the measured convention factor
#     cF_SIMPLE / cF_1D = 534.8 / 472.7 = 1.131   (G_7_6, Shanghai-validated)
# Validated end-to-end on D_7_6 (17 cases): production RBF extrapolation
# dP RMSRE 67.4% / bias +64%  ->  override 454.3 gives 14.1% / +0.2%
# (HISTORICAL/SUPERSEDED — d76 gate later re-baselined to ≈11.29% / −7.5%).
# The RBF kernel and its col47-convention anchors are UNTOUCHED; this is a
# thin query-level layer with a local Gaussian influence region (log-space
# blend, exact at the calibrated point, hard zero beyond w<0.05 so existing
# anchor-point values are bit-identical).  Scalar path only — the vectorised
# predict_K_cF_vec (zoned/continuous-field designs) keeps the pure RBF.
# Disable with TPMSHX_DF_OVERRIDES=0.

_OVERRIDES: dict[str, list[tuple[float, float, float]]] = {
    # tpms: [(L_mm, t_mm, cF_calibrated), ...]
    #
    # EMPTY (2026-06-11): a Diamond (7.0, 0.6, 454.3) entry from the D_7_6
    # specimen experiment was landed and then REVERTED the same day — that
    # value is total-dP convention (specimen incl. manifolds), while the
    # production target convention is CORE-only dP.  The mechanism stays for
    # future core-clean calibrations (e.g. rough-wall CFD).  Known open issue
    # documented by validation/validate_d76_3d.py: the pure RBF extrapolation
    # at Diamond L7/t0.6 over-predicts the specimen total dP by ~1.86x.
}
_OVR_TAU_L = 0.5    # influence radius in L [mm]
_OVR_TAU_T = 0.08   # influence radius in t [mm]
_OVR_W_MIN = 0.05   # below this weight the override is exactly off


def _overrides_enabled() -> bool:
    return os.environ.get("TPMSHX_DF_OVERRIDES", "1").strip() != "0"


def _apply_override(tpms: str, L_mm: float, t_mm: float,
                    cF_rbf: float) -> float:
    """Blend end-to-end calibrated cF over a local region; RBF elsewhere."""
    if not _overrides_enabled():
        return cF_rbf
    from math import exp, log10
    best_w, best_cf = 0.0, cF_rbf
    for (Lo, to, cfo) in _OVERRIDES.get(tpms, ()):
        dL = (L_mm - Lo) / _OVR_TAU_L
        dt = (t_mm - to) / _OVR_TAU_T
        w = exp(-(dL * dL + dt * dt))
        if w > best_w:
            best_w, best_cf = w, cfo
    if best_w < _OVR_W_MIN:
        return cF_rbf
    return 10.0 ** (best_w * log10(best_cf) + (1.0 - best_w) * log10(cF_rbf))


# ==================================================================
# Backend selection — explicit registry (B2 2.2; see backend.py for the
# registration contract: Shanghai 3D + D_7_6 gates required for any new
# backend or default switch).
# ==================================================================

from .backend import available_methods, get_backend  # noqa: E402

_DF_DEFAULT = "gamma_df"     # default switched rbf -> gamma_df 2026-06-12


def _resolve_method(method: str | None = None) -> str:
    """Per-call ``method`` wins; else env TPMSHX_DF_METHOD; else default."""
    m = (method if method is not None
         else os.environ.get("TPMSHX_DF_METHOD", _DF_DEFAULT)).strip().lower()
    if m not in available_methods():
        raise ValueError(f"unknown DF method {m!r}; "
                         f"valid: {available_methods()}")
    return m


def _get_model(tpms_type: str, method: str | None = None):
    """Return the cached surrogate backend for (tpms_type, method).

    Returns a :class:`backend.DFBackend`; unknown attributes pass through
    to the wrapped model, so diagnostic call sites (``._rbf_K``,
    ``.K_min``, ``.summary()``) keep working unchanged.
    """
    return get_backend(tpms_type, _resolve_method(method))


# ==================================================================
# Public API
# ==================================================================

def predict_K_cF(tpms_type: str, L_mm: float, t_mm: float,
                 eps_f: float, method: str | None = None
                 ) -> tuple[float, float]:
    """Return (K [m^2], c_F [1/m]) for this geometry.

    method: None (env TPMSHX_DF_METHOD, default "gamma_df") | "rbf"
    | "gamma_df".
    c_F passes through the end-to-end calibrated override layer (see
    _OVERRIDES above) regardless of backend; outside the override
    regions this is the pure backend value.
    """
    K, cF = _get_model(tpms_type, method).predict(L_mm, t_mm, eps_f)
    return K, _apply_override(tpms_type, L_mm, t_mm, cF)


def predict_K_cF_vec(tpms_type: str, L_mm: np.ndarray, t_mm: np.ndarray,
                     eps_f: np.ndarray, method: str | None = None
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised variant for solver iteration over grid cells.

    Shape-agnostic: accepts any compatible array shape (1D, 2D, 3D). The
    returned (K, c_F) arrays match the input shape. Inputs are broadcast
    together.

    Performance (2026-05-28 audit Item 2 / H2): native RBF batched eval
    replaces the per-cell Python loop. ~50× faster on Shanghai-shaped
    grids — the RBFInterpolator kernel matmul vectorises naturally over
    a (N, 3) query array, so we hand it the whole batch at once.

    method="gamma_df": evaluated per unique (L, t) pair with a local
    cache — exact, fast for zoned/uniform designs; continuous-field
    designs with many distinct cells fall back to per-pair cost.
    """
    L_arr = np.asarray(L_mm, dtype=np.float64)
    t_arr = np.asarray(t_mm, dtype=np.float64)
    e_arr = np.asarray(eps_f, dtype=np.float64)
    shape = np.broadcast(L_arr, t_arr, e_arr).shape

    # B2 2.2: per-backend vectorisation lives in backend.predict_vec
    # (rbf: native batch + internal K clamp; gamma_df: unique-pair cache).
    model = _get_model(tpms_type, method)
    K, cF = model.predict_vec(
        np.broadcast_to(L_arr, shape).ravel(),
        np.broadcast_to(t_arr, shape).ravel(),
        np.broadcast_to(e_arr, shape).ravel(),
    )
    return K.reshape(shape), cF.reshape(shape)


def predict_dP(tpms_type: str, L_mm: float, t_mm: float, eps_f: float,
               u: float, rho: float, mu: float,
               L_channel_m: float, method: str | None = None) -> float:
    """Compute dP via incompressible D-F (backward-compatible interface).

    For compressible flow, use predict_dP_compressible instead.
    """
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f, method=method)
    return (mu * u / K + rho * c_F * u ** 2) * L_channel_m


def predict_dP_compressible(tpms_type: str, L_mm: float, t_mm: float,
                            eps_f: float, G: float, T: float,
                            P_in: float, mu: float,
                            L: float, strict: bool = False,
                            method: str | None = None) -> float:
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
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f, method=method)
    C = mu * G / K + c_F * G ** 2
    P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L
    if P_out_sq <= 0:
        # Codex #6: infeasible (no real P_out). strict → NaN for
        # detect+exclude+count; default → legacy P_in (optimizer untouched).
        # Robustness (2026-06-25): the non-strict P_in rescue used to be
        # silent. Warn once so a choked operating point isn't mistaken for a
        # genuine dP ≈ P_in result.
        _choke_key = (tpms_type, round(float(L_mm), 2), round(float(t_mm), 2))
        if _choke_key not in _CHOKE_WARNED:
            _CHOKE_WARNED.add(_choke_key)
            warnings.warn(
                f"[D-F choke] 1D compressible dP infeasible "
                f"(P_out^2={P_out_sq:.3e} <= 0, predicted dP >= P_in): the flow "
                "is choked at these conditions; returning P_in as the dP "
                "rescue. Reduce velocity/length or raise inlet pressure.",
                stacklevel=2)
        return float('nan') if strict else P_in
    dP_baseline = P_in - sqrt(P_out_sq)

    if not _residual_correction_enabled():
        return dP_baseline

    # FIX (2026-06-24 audit): the residual corrector g() is fit against the RBF
    # baseline (residual_correction._build builds SurrogateV3 method='rbf' with
    # g=(actual-pred_rbf)/pred_rbf). Multiplying it onto a non-rbf baseline (the
    # production default flipped rbf->gamma_df on 2026-06-12) is a backend
    # mismatch that corrupts rather than corrects. Only apply when the ACTIVE
    # backend is actually rbf; gamma_df already bakes the closure into K/cF.
    if _resolve_method(method) != 'rbf':
        return dP_baseline

    # Apply residual learning correction (rbf baseline only)
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
