"""
surrogate_v3.py — Production surrogate for Darcy-Forchheimer coefficients.

Model:
    1D compressible isothermal D-F equation:
        P_out² = P_in² − 2·R·T·(μG/K + c_F·G²)·L

    c_F: RBF exact interpolation on (L_mm, t_mm, eps_f)
    K:   RBF interpolation + clamp K_min = 1e-7
         (physical basis: Darcy fraction ≤ 15% at lowest operational Re)

Velocity / mass-flux convention:
    G = m_dot / A_void (interstitial mass flux), i.e. A_void already absorbs
    the eps_f factor. Consequently the fitted K and c_F are *effective
    interstitial* coefficients — not canonical Darcy/Forchheimer values.
    Downstream consumers (simple_solver.py) use the same convention; do not
    mix with superficial-form equations from textbooks.

Calibration:
    1. Compressible WLS on raw Pressureloss_TPMS (col 43) + G (col 48):
       (P_in² - P_out²) / (2·R·T·L_ch) = μG/K + c_F·G²
    2. Multiply by boundary effect coefficient alpha:
       c_F_final = alpha × c_F_raw
       K_final = K_raw / alpha
    3. L=8 geometries: Re < 1600 excluded (transition regime)

Usage:
    >>> from sjtu_tpmshx.df_fit.surrogate_v3 import SurrogateV3
    >>> model = SurrogateV3()
    >>> K, c_F = model.predict(L_mm=7.0, t_mm=0.6)
    >>> dP = model.predict_dP(K, c_F, G=63.05, T=370.7, P_in=304746, mu=2.16e-5, L=0.182)
"""
from __future__ import annotations

import sys
import warnings
from math import isfinite, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent

# Make sjtu_tpmshx/ importable as a search root so `from solvers.tpms_calc`
# below resolves regardless of how the app was launched (python main.py from
# sjtu_tpmshx/, python -m sjtu_tpmshx.main from parent, or packaged entry).
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scipy.interpolate import RBFInterpolator
from solvers.tpms_calc import geometry as tpms_geometry, air_viscosity, P_atm

R_AIR = 287.05
K_S_CELLS = 10
P_ATM = P_atm
_KS = 16.0
K_MIN = 1e-8  # TEMPORARY: lowered from 1e-7 to let L>=5 use real K. Revisit later.

XLSX = _PROJECT / "data" / "raw_data" / "试验记录表_整理版.xlsx"


class SurrogateV3:
    """Production surrogate: RBF(c_F) + RBF(K) with K clamp."""

    def __init__(self, tpms: str = "Gyroid", K_min: float = K_MIN):
        self.tpms = tpms
        self.K_min = K_min
        self._build()

    def _build(self) -> None:
        """Load data, calibrate, build RBF interpolators."""
        # Load boundary effect coefficients
        alpha_df = pd.read_excel(
            str(XLSX), engine="openpyxl",
            sheet_name="边界效应系数", header=None)
        alpha_map = {str(r.iloc[0]): float(r.iloc[1])
                     for _, r in alpha_df.iterrows()}

        # Load training data
        prefix = self.tpms[0]  # 'G' for Gyroid, 'D' for Diamond
        sheet = f"{self.tpms}_汇总"
        raw = pd.read_excel(
            str(XLSX), engine="openpyxl",
            sheet_name=sheet, header=None, skiprows=1)

        L_col = pd.to_numeric(raw.iloc[:, 1], errors="coerce")
        mask = L_col.notna()
        L_mm = L_col[mask].astype(float).values
        t_mm = pd.to_numeric(raw.iloc[:, 2], errors="coerce")[mask].astype(float).values
        T_C = pd.to_numeric(raw.iloc[:, 7], errors="coerce")[mask].astype(float).values
        # 2026-05-28 G convention fix: previous code read col 48 ("G
        # 千克每平方米每秒") which in the v3.1 xlsx is ≈ 20× ρ·v — an
        # interstitial-throat mass flux that does not match the doc
        # convention. The vault method spec (2026-04-16) and LOO table
        # use G = ρ·u = m/(A_total) (superficial). Reconstruct it from
        # col 12 (density) and col 13 (velocity) so the fit ranges
        # match the documented c_F = 186–2140 for trained geometries.
        rho_col = pd.to_numeric(raw.iloc[:, 12], errors="coerce")[mask].astype(float).values
        v_col = pd.to_numeric(raw.iloc[:, 13], errors="coerce")[mask].astype(float).values
        G = rho_col * v_col
        dP_raw = pd.to_numeric(raw.iloc[:, 43], errors="coerce")[mask].astype(float).values
        Re = pd.to_numeric(raw.iloc[:, 3], errors="coerce")[mask].astype(float).values

        valid = ~(np.isnan(G) | np.isnan(dP_raw) | np.isnan(T_C) | np.isnan(Re))
        L_mm, t_mm, T_C, G, dP_raw, Re = (
            a[valid] for a in (L_mm, t_mm, T_C, G, dP_raw, Re))
        T_K = T_C + 273.15
        mu = np.array([air_viscosity(T) for T in T_K])

        # L=8: exclude Re < 1600
        keep = ~((L_mm == 8) & (Re < 1600))
        L_mm, t_mm, G, dP_raw, T_K, mu = (
            a[keep] for a in (L_mm, t_mm, G, dP_raw, T_K, mu))

        # Per-geometry calibration: fit on raw dP, then × alpha
        ref_list = []
        self._rows_list = []
        self._geom_cache = {}

        for L_val in sorted(np.unique(L_mm)):
            for t_val in sorted(np.unique(t_mm[L_mm == L_val])):
                sel = (L_mm == L_val) & (t_mm == t_val)
                if sel.sum() < 3:
                    continue

                key = f"{prefix}_{int(L_val)}_{int(t_val * 10):02d}"
                alpha = alpha_map.get(key, 1.0)
                g = tpms_geometry(self.tpms, float(L_val), float(t_val), _KS)
                self._geom_cache[(float(L_val), float(t_val))] = g
                L_ch = K_S_CELLS * L_val * 1e-3

                gs = G[sel]; mu_s = mu[sel]; T_s = T_K[sel]; dp_s = dP_raw[sel]
                P_in = P_ATM + dp_s
                lhs = (P_in ** 2 - P_ATM ** 2) / (2 * R_AIR * T_s * L_ch)
                X = np.column_stack([mu_s * gs, gs ** 2])
                w = 1.0 / lhs
                coef, *_ = np.linalg.lstsq(X * w[:, None], lhs * w, rcond=None)
                inv_K_raw, cF_raw = coef

                cF_corr = alpha * cF_raw
                K_corr = ((1.0 / inv_K_raw) / alpha
                          if inv_K_raw > 0 else None)

                ref_list.append(dict(
                    L_mm=float(L_val), t_mm=float(t_val),
                    eps_f=g["epsilon"] / 2, r_h_m=g["D_h"] / 2,
                    K=K_corr, c_F=max(cF_corr, 1.0)))

                # Store corrected training rows
                for i in np.where(sel)[0]:
                    dp_corr = dP_raw[i] * alpha
                    self._rows_list.append(dict(
                        L_mm=L_mm[i], t_mm=t_mm[i],
                        eps_f=g["epsilon"] / 2,
                        G=G[i], mu=mu[i], T=T_K[i],
                        P_in=P_ATM + dp_corr, dP=dp_corr,
                        L_ch=K_S_CELLS * L_mm[i] * 1e-3))

        self.ref = pd.DataFrame(ref_list)
        self.rows_df = pd.DataFrame(self._rows_list)

        # Handle K=None (unconstrained) via power-law extrapolation
        K_arr = self.ref["K"].to_numpy(dtype=float)
        D_h_arr = np.array([2 * r.r_h_m for _, r in self.ref.iterrows()])
        has_K = ~np.isnan(K_arr)
        if not has_K.all():
            Xpw = np.column_stack([np.ones(has_K.sum()),
                                    np.log10(D_h_arr[has_K])])
            ypw = np.log10(K_arr[has_K])
            cpw, *_ = np.linalg.lstsq(Xpw, ypw, rcond=None)
            for i in range(len(self.ref)):
                if not has_K[i]:
                    K_arr[i] = 10.0 ** (cpw[0] + cpw[1] * np.log10(D_h_arr[i]))

        # Build RBF interpolators
        X_feat = self.ref[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float)
        self._rbf_K = RBFInterpolator(
            X_feat, np.log10(K_arr),
            kernel="cubic", smoothing=0.1)
        self._rbf_cF = RBFInterpolator(
            X_feat, np.log10(self.ref["c_F"].to_numpy()),
            kernel="cubic", smoothing=0.1)

    def predict(self, L_mm: float, t_mm: float,
                eps_f: float | None = None) -> tuple[float, float]:
        """Predict (K, c_F) for a geometry.

        Parameters
        ----------
        L_mm, t_mm : unit cell size and wall thickness [mm]
        eps_f : single-channel porosity. If None, computed from geometry.

        Returns
        -------
        K : Darcy permeability [m²], clamped to K_min
        c_F : Forchheimer coefficient [1/m]
        """
        if eps_f is None:
            g = tpms_geometry(self.tpms, L_mm, t_mm, _KS)
            eps_f = g["epsilon"] / 2.0

        x = np.array([[L_mm, t_mm, eps_f]])
        K = max(10.0 ** float(self._rbf_K(x)[0]), self.K_min)
        c_F = 10.0 ** float(self._rbf_cF(x)[0])
        return K, c_F

    @staticmethod
    def predict_dP(K: float, c_F: float, G: float, T: float,
                   P_in: float, mu: float, L: float,
                   strict: bool = False) -> float:
        """1D compressible isothermal D-F pressure drop.

        Parameters
        ----------
        K : permeability [m²]
        c_F : Forchheimer coefficient [1/m]
        G : mass flux [kg/(m²·s)]
        T : temperature [K]
        P_in : inlet absolute pressure [Pa]
        mu : dynamic viscosity [Pa·s]
        L : channel length [m]

        Returns
        -------
        dP : pressure drop [Pa]
        """
        C = mu * G / K + c_F * G ** 2
        P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L
        if P_out_sq <= 0:
            # Physically infeasible (choked / over-driven): no real P_out.
            # Codex #6: strict → NaN so callers can detect+exclude+count;
            # default → legacy P_in rescue (optimizer value-path untouched).
            return float('nan') if strict else P_in
        return P_in - sqrt(P_out_sq)

    def summary(self) -> None:
        """Print model summary."""
        print(f"SurrogateV3 ({self.tpms})")
        print(f"  Geometries: {len(self.ref)}")
        print(f"  Training rows: {len(self.rows_df)}")
        print(f"  K_min: {self.K_min:.0e}")
        print(f"\n  Per-geometry (K, c_F):")
        print(f"  {'L':>3} {'t':>4} {'K':>10} {'c_F':>8}")
        for _, r in self.ref.iterrows():
            K_str = f"{r.K:.3e}" if r.K is not None and not np.isnan(r.K) else "N/A"
            print(f"  {r.L_mm:3.0f} {r.t_mm:4.1f} {K_str:>10} {r.c_F:8.1f}")


# ==================================================================
# Evaluation helpers
# ==================================================================

def eval_shanghai(model: SurrogateV3, L: float = 7.0, t: float = 0.6):
    """Evaluate on Shanghai 16 cases."""
    sh_xlsx = _PROJECT / "data" / "raw_data" / \
              "20260401-上海电气天然气加热器实验工况.xlsx"
    sh = pd.read_excel(str(sh_xlsx), engine="openpyxl",
                       sheet_name="Sheet1", header=None, skiprows=2)
    # Canonical Shanghai params: see configs/shanghai_baseline.json
    # (n_units=36, a_flow_per_unit_m2=1.80565e-5, L_dom_m=0.182). Not loaded
    # here to keep eval_shanghai a zero-dependency standalone helper; if
    # the JSON drifts, this constant must follow.
    A_FLOW = 36 * 18.0565e-6
    L_DOM = 0.182  # Shanghai HX streamwise A length [m]. Was 0.231 (stale —
                   # 182+42+7 historical "total" guess); corrected 2026-05-28.

    K, c_F = model.predict(L, t)
    print(f"K = {K:.4e}, c_F = {c_F:.2f}")

    err_sq = 0.0
    n_valid = 0
    n_invalid = 0
    results = []
    for ci in range(16):
        m = float(sh.iloc[ci, 5])
        T = float(sh.iloc[ci, 28]) + 273.15
        P_in = P_ATM + float(sh.iloc[ci, 30])
        dP_exp = float(sh.iloc[ci, 30]) - float(sh.iloc[ci, 31])
        G = m / A_FLOW
        mu = air_viscosity(T)

        # Codex #6: strict → NaN on infeasible; exclude+count, never
        # fold a rescued P_in into RMSRE.
        dP_pred = model.predict_dP(K, c_F, G, T, P_in, mu, L_DOM,
                                   strict=True)
        if not isfinite(dP_pred):
            n_invalid += 1
            results.append(dict(case=ci + 1, dP_exp=dP_exp,
                                dP_pred=float('nan'), err_pct=float('nan'),
                                pressure_state_valid=False))
            continue
        err = (dP_pred - dP_exp) / dP_exp
        err_sq += err ** 2
        n_valid += 1
        results.append(dict(case=ci + 1, dP_exp=dP_exp,
                            dP_pred=dP_pred, err_pct=err * 100,
                            pressure_state_valid=True))

    rmsre = (sqrt(err_sq / n_valid) * 100) if n_valid else float('nan')
    if n_invalid:
        print(f"  ⚠ {n_invalid}/16 cases infeasible (P_out²≤0) — "
              f"excluded from RMSRE (computed over {n_valid} valid)")
    return rmsre, results


def eval_loo(model: SurrogateV3):
    """Leave-one-geometry-out evaluation."""
    ref = model.ref
    rows_df = model.rows_df
    X_feat = ref[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float)

    # Rebuild K array for LOO
    K_arr = ref["K"].to_numpy(dtype=float)
    D_h_arr = np.array([2 * r.r_h_m for _, r in ref.iterrows()])
    has_K = ~np.isnan(K_arr)
    if not has_K.all():
        Xpw = np.column_stack([np.ones(has_K.sum()),
                                np.log10(D_h_arr[has_K])])
        ypw = np.log10(K_arr[has_K])
        cpw, *_ = np.linalg.lstsq(Xpw, ypw, rcond=None)
        for i in range(len(ref)):
            if not has_K[i]:
                K_arr[i] = 10.0 ** (cpw[0] + cpw[1] * np.log10(D_h_arr[i]))

    log_K = np.log10(K_arr)
    log_cF = np.log10(ref["c_F"].to_numpy())

    mapes = []
    for idx in range(len(ref)):
        r = ref.iloc[idx]
        mask = np.ones(len(ref), dtype=bool)
        mask[idx] = False

        rbf_K_i = RBFInterpolator(
            X_feat[mask], log_K[mask],
            kernel="cubic", smoothing=0.1)
        rbf_cF_i = RBFInterpolator(
            X_feat[mask], log_cF[mask],
            kernel="cubic", smoothing=0.1)

        K_p = max(10.0 ** rbf_K_i(X_feat[idx:idx + 1])[0], model.K_min)
        cF_p = 10.0 ** rbf_cF_i(X_feat[idx:idx + 1])[0]

        grp = rows_df[(rows_df["L_mm"] == r.L_mm) &
                       (rows_df["t_mm"] == r.t_mm)]
        Gt = grp["G"].to_numpy()
        Tt = grp["T"].to_numpy()
        mut = grp["mu"].to_numpy()
        Pit = grp["P_in"].to_numpy()
        dPt = grp["dP"].to_numpy()
        Lct = grp["L_ch"].to_numpy()

        C = mut * Gt / K_p + cF_p * Gt ** 2
        Psq = Pit ** 2 - 2 * R_AIR * Tt * C * Lct
        # Codex #6: rows with Psq≤0 are infeasible — exclude them from the
        # LOO MAPE instead of np.maximum(Psq,0)-rescuing into a fake dP.
        _ok = Psq > 0
        if not _ok.any():
            mape = float('nan')
        else:
            dPp = Pit[_ok] - np.sqrt(Psq[_ok])
            mape = float(np.mean(np.abs(dPp - dPt[_ok]) / dPt[_ok]) * 100)
        if not _ok.all():
            print(f"  ⚠ L={r.L_mm:.0f} t={r.t_mm:.1f}: "
                  f"{int((~_ok).sum())}/{_ok.size} pts infeasible — excluded")
        mapes.append(mape)
        print(f"  L={r.L_mm:.0f} t={r.t_mm:.1f}: "
              f"K={K_p:.3e} cF={cF_p:.0f} MAPE={mape:.1f}%")

    return float(np.nanmean(mapes))  # Codex #6: skip fully-infeasible geoms


# ==================================================================
# CLI
# ==================================================================

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

    model = SurrogateV3()
    model.summary()

    # Shanghai
    print("\n=== Shanghai ===")
    K, c_F = model.predict(7.0, 0.6)
    print(f"Prediction: K={K:.4e}, c_F={c_F:.2f}")
    rmsre, results = eval_shanghai(model)
    print(f"\n{'C':>2} {'dP_exp':>9} {'dP_pred':>9} {'err%':>8}")
    print("-" * 35)
    for r in results:
        print(f"{r['case']:2d} {r['dP_exp']:9.0f} {r['dP_pred']:9.0f} "
              f"{r['err_pct']:+8.1f}%")
    print(f"\n  Shanghai RMSRE = {rmsre:.2f}%")

    # LOO
    print("\n=== LOO ===")
    loo_mape = eval_loo(model)
    print(f"\n  Mean LOO MAPE = {loo_mape:.2f}%")

    print(f"\n=== Final ===")
    print(f"  Shanghai RMSRE = {rmsre:.2f}%")
    print(f"  LOO MAPE = {loo_mape:.2f}%")


if __name__ == "__main__":
    main()
