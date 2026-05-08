"""LOO validation for ResidualCorrector.

For each (TPMS, L, t) geometry: hold it out, train corrector on remaining
~22 geometries, predict dP for the held-out points, measure error.

Compare to baseline LOO (no corrector).
"""
from __future__ import annotations

import sys
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scipy.interpolate import RBFInterpolator

from solvers.tpms_calc import geometry as tpms_geometry  # noqa: E402

R_AIR = 287.05
_KS = 16.0


def loo_test(tpms: str = "Gyroid"):
    """LOO over geometries: hold out (L, t), refit corrector + surrogate."""
    from .surrogate_v3 import SurrogateV3
    from .residual_correction import ResidualCorrector

    sv3_full = SurrogateV3(tpms=tpms)
    rows_full = sv3_full.rows_df.copy()
    geoms = sorted(set(zip(rows_full["L_mm"], rows_full["t_mm"])))

    print(f"=== LOO test ({tpms}, {len(geoms)} geometries) ===")
    print(f"  baseline (no corrector) vs corrected dP errors")

    results = []
    for L_test, t_test in geoms:
        # Held-out rows
        sel_test = (rows_full["L_mm"] == L_test) & (rows_full["t_mm"] == t_test)
        test_rows = rows_full[sel_test]
        train_rows = rows_full[~sel_test]
        if len(test_rows) < 1 or len(train_rows) < 5:
            continue

        # ---- Baseline: predict_K_cF using SurrogateV3 trained without held-out ----
        # SurrogateV3 trains on raw Excel — to do LOO on K/cF we'd refit. For
        # speed, we approximate by directly fitting RBF on 23 rows of `ref`.
        ref_full = sv3_full.ref.copy()
        ref_train = ref_full[~((ref_full["L_mm"] == L_test) &
                                (ref_full["t_mm"] == t_test))]

        X_train = ref_train[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float)
        K_train_log = np.log10(ref_train["K"].to_numpy(dtype=float))
        cF_train_log = np.log10(ref_train["c_F"].to_numpy(dtype=float))
        if len(X_train) < 3:
            continue
        rbf_K_loo = RBFInterpolator(X_train, K_train_log, kernel="thin_plate_spline", smoothing=0)
        rbf_cF_loo = RBFInterpolator(X_train, cF_train_log, kernel="thin_plate_spline", smoothing=0)

        # Predict K, cF for held-out geometry
        eps_f_test = float(test_rows["eps_f"].iloc[0])
        x_test = np.array([[L_test, t_test, eps_f_test]])
        K_loo = max(10.0 ** float(rbf_K_loo(x_test)[0]), 1e-8)
        cF_loo = 10.0 ** float(rbf_cF_loo(x_test)[0])

        # Compute baseline dP for each held-out CFD point
        baseline_errs = []
        log_Re_list = []
        for _, row in test_rows.iterrows():
            G = float(row["G"]); mu = float(row["mu"]); T = float(row["T"])
            P_in = float(row["P_in"]); L_ch = float(row["L_ch"])
            dP_actual = float(row["dP"])
            C = mu * G / K_loo + cF_loo * G * G
            P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L_ch
            if P_out_sq <= 0:
                continue
            dP_pred = P_in - sqrt(P_out_sq)
            err = (dP_pred - dP_actual) / dP_actual
            baseline_errs.append(err)
            geom = tpms_geometry(tpms, L_test, t_test, _KS)
            D_h = float(geom["D_h"])
            rho_in = P_in / (R_AIR * T)
            u_in = G / rho_in
            Re = rho_in * u_in * D_h / mu
            log_Re_list.append(np.log10(Re))

        baseline_mae = float(np.mean(np.abs(baseline_errs))) * 100 if baseline_errs else float('nan')
        baseline_rmse = float(np.sqrt(np.mean(np.square(baseline_errs)))) * 100 if baseline_errs else float('nan')

        # ---- Corrected: corrector trained on rows EXCLUDING (L_test, t_test) ----
        # Build corrector on training subset
        train_log_Re = []
        train_eps_f = []
        train_g = []
        for _, row in train_rows.iterrows():
            L_mm = float(row["L_mm"])
            t_mm = float(row["t_mm"])
            eps_f = float(row["eps_f"])
            G = float(row["G"]); mu = float(row["mu"]); T = float(row["T"])
            P_in = float(row["P_in"]); L_ch = float(row["L_ch"])
            dP_actual = float(row["dP"])
            # Use full-data sv3 prediction (this is SurrogateV3 trained on all 24 rows)
            # For pure LOO, ideally we'd re-train SV3 too — but it's expensive.
            # We use the same (K, cF) at this geometry, residual is fit error vs
            # the row's training points (in-sample for that row).
            K_b, cF_b = sv3_full.predict(L_mm, t_mm, eps_f)
            C = mu * G / K_b + cF_b * G * G
            P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L_ch
            if P_out_sq <= 0:
                continue
            dP_pred = P_in - sqrt(P_out_sq)
            if dP_actual <= 0 or dP_pred <= 0:
                continue
            g_t = (dP_actual - dP_pred) / dP_pred
            geom = tpms_geometry(tpms, L_mm, t_mm, _KS)
            D_h = float(geom["D_h"])
            rho_in = P_in / (R_AIR * T)
            u = G / rho_in
            Re = rho_in * u * D_h / mu
            train_log_Re.append(np.log10(Re))
            train_eps_f.append(eps_f)
            train_g.append(g_t)

        if len(train_g) < 10:
            continue
        rbf_corr = RBFInterpolator(
            np.column_stack([train_log_Re, train_eps_f]),
            np.array(train_g),
            kernel="thin_plate_spline", smoothing=1.0)

        # Apply correction to held-out predictions
        corrected_errs = []
        for _, row in test_rows.iterrows():
            G = float(row["G"]); mu = float(row["mu"]); T = float(row["T"])
            P_in = float(row["P_in"]); L_ch = float(row["L_ch"])
            dP_actual = float(row["dP"])
            C = mu * G / K_loo + cF_loo * G * G
            P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L_ch
            if P_out_sq <= 0:
                continue
            dP_pred = P_in - sqrt(P_out_sq)
            geom = tpms_geometry(tpms, L_test, t_test, _KS)
            D_h = float(geom["D_h"])
            rho_in = P_in / (R_AIR * T)
            u = G / rho_in
            Re = rho_in * u * D_h / mu
            log_Re = np.log10(max(Re, 1.0))
            x_q = np.atleast_2d([log_Re, eps_f_test])
            g = float(rbf_corr(x_q)[0])
            g = float(np.clip(g, -0.6, 0.6))
            dP_corrected = dP_pred * (1.0 + g)
            err = (dP_corrected - dP_actual) / dP_actual
            corrected_errs.append(err)

        corrected_mae = float(np.mean(np.abs(corrected_errs))) * 100 if corrected_errs else float('nan')
        corrected_rmse = float(np.sqrt(np.mean(np.square(corrected_errs)))) * 100 if corrected_errs else float('nan')

        results.append(dict(L=L_test, t=t_test,
                            baseline_mae=baseline_mae,
                            baseline_rmse=baseline_rmse,
                            corrected_mae=corrected_mae,
                            corrected_rmse=corrected_rmse))
        print(f"  L={L_test} t={t_test}: "
              f"baseline MAE {baseline_mae:5.2f}% / RMSE {baseline_rmse:5.2f}%   "
              f"corrected MAE {corrected_mae:5.2f}% / RMSE {corrected_rmse:5.2f}%")

    if results:
        df = pd.DataFrame(results)
        bMAE = float(df["baseline_mae"].mean())
        cMAE = float(df["corrected_mae"].mean())
        bRMSE = float(df["baseline_rmse"].mean())
        cRMSE = float(df["corrected_rmse"].mean())
        print()
        print(f"  AVG baseline:  MAE {bMAE:5.2f}%  RMSE {bRMSE:5.2f}%")
        print(f"  AVG corrected: MAE {cMAE:5.2f}%  RMSE {cRMSE:5.2f}%")
        delta_MAE = bMAE - cMAE
        print(f"  Δ MAE: {delta_MAE:+.2f}pp ({'improvement' if delta_MAE > 0 else 'regression'})")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    loo_test("Gyroid")
    print()
    loo_test("Diamond")
