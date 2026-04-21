"""
retrain_v2.py — MLP surrogate with compressible G-based D-F calibration
+ boundary effect correction.

Calibration:
    (P_in² - P_out²) / (2·R·T·L_ch) = μG/K + c_F·G²

    - G from Excel col 48 (AW: mass flux kg/(m²·s))
    - dP from Excel col 43 (AR: Pressureloss_TPMS) × alpha (boundary coeff)
    - P_in = P_atm + alpha·dP_raw,  P_out = P_atm
    - T = inlet temperature (col 7), isothermal assumption
    - alpha from sheet '边界效应系数'

MLP predicts c_F only (K unconstrained in Forchheimer-dominated regime).
Loss = mean squared relative dP error using 1D compressible formula.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import Adam

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry, air_viscosity, P_atm  # noqa: E402

R_AIR = 287.05
K_S_CELLS = 10
P_ATM = P_atm
_KS = 16.0

XLSX = _PROJECT / "data" / "raw_data" / "试验记录表_整理版.xlsx"

# Training hyper-params
HIDDEN = 32
DROPOUT = 0.05
LR = 1e-3
WEIGHT_DECAY = 3e-4
EPOCHS = 8000
PATIENCE = 800
N_ENSEMBLE = 5
SEED = 20260416


class CFMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(3, HIDDEN), nn.SiLU(), nn.Dropout(DROPOUT),
            nn.Linear(HIDDEN, HIDDEN), nn.SiLU(), nn.Dropout(DROPOUT),
            nn.Linear(HIDDEN, 1),
        )

    def forward(self, x):
        return self.net(x)


# ==================================================================
# Data loading
# ==================================================================

def _load_alpha() -> dict[str, float]:
    """Load boundary effect coefficients from '边界效应系数' sheet."""
    df = pd.read_excel(str(XLSX), engine="openpyxl",
                       sheet_name="边界效应系数", header=None)
    return {str(r.iloc[0]): float(r.iloc[1]) for _, r in df.iterrows()}


def load_gyroid_v2() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load Gyroid training data with corrected dP.

    Returns (per_row_df, per_geom_ref).
    """
    alpha_map = _load_alpha()

    raw = pd.read_excel(str(XLSX), engine="openpyxl",
                        sheet_name="Gyroid_汇总", header=None, skiprows=1)

    L_col = pd.to_numeric(raw.iloc[:, 1], errors="coerce")
    mask = L_col.notna()
    L_mm = L_col[mask].astype(float).values
    t_mm = pd.to_numeric(raw.iloc[:, 2], errors="coerce")[mask].astype(float).values
    T_C = pd.to_numeric(raw.iloc[:, 7], errors="coerce")[mask].astype(float).values
    G = pd.to_numeric(raw.iloc[:, 48], errors="coerce")[mask].astype(float).values
    dP_raw = pd.to_numeric(raw.iloc[:, 43], errors="coerce")[mask].astype(float).values

    valid = ~(np.isnan(G) | np.isnan(dP_raw) | np.isnan(T_C))
    L_mm, t_mm, T_C, G, dP_raw = (a[valid] for a in (L_mm, t_mm, T_C, G, dP_raw))
    T_K = T_C + 273.15
    mu = np.array([air_viscosity(T) for T in T_K])

    # Apply boundary effect correction per geometry
    alpha = np.ones(len(L_mm))
    for i in range(len(L_mm)):
        key = f"G_{int(L_mm[i])}_{int(t_mm[i] * 10):02d}"
        if key in alpha_map:
            alpha[i] = alpha_map[key]
    dP_corr = dP_raw * alpha

    # Build per-row DataFrame
    rows_list = []
    geom_cache = {}
    for i in range(len(L_mm)):
        key = (float(L_mm[i]), float(t_mm[i]))
        if key not in geom_cache:
            geom_cache[key] = tpms_geometry("Gyroid", key[0], key[1], _KS)
        g = geom_cache[key]
        rows_list.append(dict(
            L_mm=L_mm[i], t_mm=t_mm[i], eps_f=g["epsilon"] / 2,
            G=G[i], mu=mu[i], T=T_K[i],
            P_in=P_ATM + dP_corr[i], dP=dP_corr[i],
            L_ch=K_S_CELLS * L_mm[i] * 1e-3,
        ))
    rows_df = pd.DataFrame(rows_list)

    # Build per-geometry reference via compressible WLS
    ref_list = []
    for (L, t), grp in rows_df.groupby(["L_mm", "t_mm"]):
        if len(grp) < 3:
            continue
        g = geom_cache[(float(L), float(t))]
        gs = grp["G"].to_numpy()
        mu_s = grp["mu"].to_numpy()
        T_s = grp["T"].to_numpy()
        P_in_s = grp["P_in"].to_numpy()
        L_ch = K_S_CELLS * float(L) * 1e-3

        lhs = (P_in_s ** 2 - P_ATM ** 2) / (2 * R_AIR * T_s * L_ch)
        X = np.column_stack([mu_s * gs, gs ** 2])
        w = 1.0 / lhs
        coef, *_ = np.linalg.lstsq(X * w[:, None], lhs * w, rcond=None)
        inv_K, c_F = coef
        K = 1.0 / max(inv_K, 1e-30) if inv_K > 0 else 1e30

        ref_list.append(dict(
            L_mm=float(L), t_mm=float(t),
            eps_f=g["epsilon"] / 2, r_h_m=g["D_h"] / 2,
            K=K, c_F=max(c_F, 1.0),
        ))
    ref_df = pd.DataFrame(ref_list)
    return rows_df, ref_df


# ==================================================================
# Training
# ==================================================================

def train_ensemble(rows_df, ref_df, base_seed=SEED, n_ensemble=N_ENSEMBLE,
                   epochs=EPOCHS, patience=PATIENCE):
    """Train c_F MLP ensemble on per-row compressible dP loss."""
    X_log = np.log10(ref_df[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float))
    Y_log = np.log10(ref_df["c_F"].to_numpy(dtype=float))
    x_mean, x_std = X_log.mean(0), X_log.std(0)
    x_std[x_std < 1e-9] = 1.0
    y_mean, y_std = Y_log.mean(), Y_log.std()

    X_rows = np.log10(rows_df[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float))
    z = torch.tensor((X_rows - x_mean) / x_std, dtype=torch.float32)
    G_t = torch.tensor(rows_df["G"].to_numpy(), dtype=torch.float32)
    T_t = torch.tensor(rows_df["T"].to_numpy(), dtype=torch.float32)
    P_in_t = torch.tensor(rows_df["P_in"].to_numpy(), dtype=torch.float32)
    dP_t = torch.tensor(rows_df["dP"].to_numpy(), dtype=torch.float32)
    L_ch_t = torch.tensor(rows_df["L_ch"].to_numpy(), dtype=torch.float32)

    models = []
    for k in range(n_ensemble):
        torch.manual_seed(base_seed + k * 101)
        np.random.seed(base_seed + k * 101)
        model = CFMLP()
        opt = Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
        sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
            opt, "min", factor=0.5, patience=patience // 4, min_lr=1e-6)
        best_loss, best_sd, wait = float("inf"), None, 0

        for ep in range(epochs):
            model.train()
            opt.zero_grad()
            out = model(z).squeeze()
            log_cF = out * y_std + y_mean
            cF = torch.pow(10.0, torch.clamp(log_cF, -2.0, 6.0))
            P_out_sq = P_in_t ** 2 - 2 * R_AIR * T_t * cF * G_t ** 2 * L_ch_t
            P_out = torch.sqrt(torch.clamp(P_out_sq, min=1e4))
            dP_pred = P_in_t - P_out
            loss = torch.mean(((dP_pred - dP_t) / dP_t) ** 2)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            lv = float(loss.item())
            sched.step(lv)
            if lv < best_loss - 1e-8:
                best_loss = lv
                best_sd = {k2: v.clone() for k2, v in model.state_dict().items()}
                wait = 0
            else:
                wait += 1
                if wait >= patience:
                    break
        if best_sd is not None:
            model.load_state_dict(best_sd)
        model.eval()
        models.append(model)

    norm = dict(x_mean=x_mean, x_std=x_std, y_mean=y_mean, y_std=y_std)
    return models, norm


def predict_cF(models, norm, L_mm, t_mm, eps_f):
    x = np.log10([[L_mm, t_mm, eps_f]])
    z = torch.tensor((x - norm["x_mean"]) / norm["x_std"], dtype=torch.float32)
    s = 0.0
    for m in models:
        with torch.no_grad():
            s += float(m(z).item()) * norm["y_std"] + norm["y_mean"]
    return float(10.0 ** (s / len(models)))


# ==================================================================
# Evaluation
# ==================================================================

def eval_shanghai(c_F: float) -> tuple[float, list[dict]]:
    """1D compressible dP evaluation on Shanghai 16 cases."""
    sh_xlsx = _PROJECT / "data" / "raw_data" / "20260401-上海电气天然气加热器实验工况.xlsx"
    sh = pd.read_excel(str(sh_xlsx), engine="openpyxl",
                       sheet_name="Sheet1", header=None, skiprows=2)
    A_FLOW = 36 * 18.0565e-6
    L_DOM = 0.231
    results = []
    err_sq = 0.0
    for ci in range(16):
        m_air = float(sh.iloc[ci, 5])
        T_K = float(sh.iloc[ci, 28]) + 273.15
        P_in = P_ATM + float(sh.iloc[ci, 30])
        dP_exp = float(sh.iloc[ci, 30]) - float(sh.iloc[ci, 31])
        G = m_air / A_FLOW
        P_out_sq = P_in ** 2 - 2 * R_AIR * T_K * c_F * G ** 2 * L_DOM
        P_out = np.sqrt(max(P_out_sq, 0))
        dP_pred = P_in - P_out
        err = (dP_pred - dP_exp) / dP_exp
        err_sq += err ** 2
        results.append(dict(case=ci + 1, dP_exp=dP_exp,
                            dP_pred=dP_pred, err_pct=err * 100))
    return float(np.sqrt(err_sq / 16) * 100), results


# ==================================================================
# Main
# ==================================================================

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

    rows_df, ref_df = load_gyroid_v2()
    print(f"Training data: {len(rows_df)} rows, {len(ref_df)} geometries")
    print("\nPer-geometry c_F (corrected calibration):")
    for _, r in ref_df.iterrows():
        print(f"  L={r.L_mm:.0f} t={r.t_mm:.1f}: c_F={r.c_F:.1f}")

    # --- Full-data training ---
    print("\n--- Full ensemble training ---")
    models, norm = train_ensemble(rows_df, ref_df)
    for k, m in enumerate(models):
        pass
    print(f"  {N_ENSEMBLE} models trained")

    # --- Predict Shanghai geometry ---
    g7 = tpms_geometry("Gyroid", 7.0, 0.6, _KS)
    cF_sh = predict_cF(models, norm, 7.0, 0.6, g7["epsilon"] / 2)
    print(f"\nMLP prediction for L=7 t=0.6: c_F = {cF_sh:.2f}")
    print(f"(linear interp L=6/8 t=0.5: 338, reverse-fit optimal: 372.7)")

    # --- Shanghai 16-case ---
    rmsre, results = eval_shanghai(cF_sh)
    print(f"\nShanghai 16 case (c_F={cF_sh:.1f}):")
    print(f"{'C':>2} {'dP_exp':>9} {'dP_pred':>9} {'err%':>8}")
    print("-" * 35)
    for r in results:
        print(f"{r['case']:2d} {r['dP_exp']:9.0f} {r['dP_pred']:9.0f} "
              f"{r['err_pct']:+8.1f}%")
    print(f"\n  Shanghai RMSRE = {rmsre:.2f}%")

    # --- LOO ---
    print("\n--- LOO on 12 Gyroid geometries ---")
    loo_mapes = []
    for idx in range(len(ref_df)):
        r = ref_df.iloc[idx]
        L_out, t_out = r.L_mm, r.t_mm

        mask_out = (rows_df["L_mm"] == L_out) & (rows_df["t_mm"] == t_out)
        train_r = rows_df[~mask_out].reset_index(drop=True)
        test_r = rows_df[mask_out].reset_index(drop=True)
        ref_tr = ref_df[~((ref_df["L_mm"] == L_out)
                          & (ref_df["t_mm"] == t_out))].reset_index(drop=True)

        ms, nm = train_ensemble(train_r, ref_tr, base_seed=SEED + idx * 7,
                                n_ensemble=3, epochs=4000, patience=400)
        cF_loo = predict_cF(ms, nm, L_out, t_out, r.eps_f)

        test_G = test_r["G"].to_numpy()
        test_T = test_r["T"].to_numpy()
        test_Pin = test_r["P_in"].to_numpy()
        test_dP = test_r["dP"].to_numpy()
        test_Lch = test_r["L_ch"].to_numpy()

        Psq = test_Pin ** 2 - 2 * R_AIR * test_T * cF_loo * test_G ** 2 * test_Lch
        dP_p = test_Pin - np.sqrt(np.maximum(Psq, 0))
        mape = float(np.mean(np.abs(dP_p - test_dP) / test_dP) * 100)
        loo_mapes.append(mape)
        print(f"  L={L_out:.0f} t={t_out:.1f}: c_F={cF_loo:.0f}, MAPE={mape:.1f}%")

    print(f"\n  Mean LOO MAPE = {np.mean(loo_mapes):.2f}%")
    print(f"\n=== Summary ===")
    print(f"  Shanghai RMSRE = {rmsre:.2f}%")
    print(f"  LOO MAPE = {np.mean(loo_mapes):.2f}%")


if __name__ == "__main__":
    main()
