"""
retrain_v3.py — MLP with corrected calibration: fit on raw col43, then × alpha.

Calibration:
    1. WLS on uncorrected Pressureloss_TPMS (col 43):
       (P_in² - P_out²)/(2RTL) = μG/K + c_F·G²
    2. c_F_final = alpha × c_F_raw  (per-geometry boundary effect coeff)

MLP predicts c_F only. Loss = compressible dP relative error.
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
import torch, torch.nn as nn
from torch.optim import Adam

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from solvers.tpms_calc import geometry as tpms_geometry, air_viscosity, P_atm

R = 287.05; K_S_CELLS = 10; P_ATM = P_atm; _KS = 16.0
XLSX = _PROJECT / "data" / "raw_data" / "试验记录表_整理版.xlsx"
SEED = 20260416


class CFMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(3, 32), nn.SiLU(), nn.Dropout(0.05),
            nn.Linear(32, 32), nn.SiLU(), nn.Dropout(0.05),
            nn.Linear(32, 1))
    def forward(self, x):
        return self.net(x)


def load_data():
    """Load Gyroid data, calibrate c_F (fit then × alpha)."""
    alpha_df = pd.read_excel(str(XLSX), engine="openpyxl",
                             sheet_name="边界效应系数", header=None)
    alpha_map = {str(r.iloc[0]): float(r.iloc[1]) for _, r in alpha_df.iterrows()}

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

    # Per-geometry: fit on raw dP, then × alpha
    geom_cache = {}
    ref_list = []
    for L_val in sorted(np.unique(L_mm)):
        for t_val in sorted(np.unique(t_mm[L_mm == L_val])):
            sel = (L_mm == L_val) & (t_mm == t_val)
            if sel.sum() < 3:
                continue
            key = f"G_{int(L_val)}_{int(t_val * 10):02d}"
            alpha = alpha_map.get(key, 1.0)
            g = tpms_geometry("Gyroid", float(L_val), float(t_val), _KS)
            geom_cache[(float(L_val), float(t_val))] = g
            L_ch = K_S_CELLS * L_val * 1e-3

            gs, mu_s, T_s, dp_s = G[sel], mu[sel], T_K[sel], dP_raw[sel]
            P_in = P_ATM + dp_s
            lhs = (P_in ** 2 - P_ATM ** 2) / (2 * R * T_s * L_ch)
            X = np.column_stack([mu_s * gs, gs ** 2])
            w = 1.0 / lhs
            coef, *_ = np.linalg.lstsq(X * w[:, None], lhs * w, rcond=None)
            cF_raw = coef[1]
            cF_corr = alpha * cF_raw

            ref_list.append(dict(
                L_mm=float(L_val), t_mm=float(t_val),
                eps_f=g["epsilon"] / 2, r_h_m=g["D_h"] / 2,
                c_F=max(cF_corr, 1.0), alpha=alpha))

    ref = pd.DataFrame(ref_list)

    # Per-row training data (use alpha-corrected dP)
    rows_list = []
    for i in range(len(L_mm)):
        k = (float(L_mm[i]), float(t_mm[i]))
        if k not in geom_cache:
            continue
        gg = geom_cache[k]
        key = f"G_{int(L_mm[i])}_{int(t_mm[i] * 10):02d}"
        alpha = alpha_map.get(key, 1.0)
        dP_corr = dP_raw[i] * alpha
        rows_list.append(dict(
            L_mm=L_mm[i], t_mm=t_mm[i], eps_f=gg["epsilon"] / 2,
            G=G[i], mu=mu[i], T=T_K[i],
            P_in=P_ATM + dP_corr, dP=dP_corr,
            L_ch=K_S_CELLS * L_mm[i] * 1e-3))

    return pd.DataFrame(rows_list), ref


def train_ensemble(rows_df, ref_df, base_seed=SEED, n_ens=5,
                   epochs=8000, patience=800):
    X_log = np.log10(ref_df[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float))
    Y_log = np.log10(ref_df["c_F"].to_numpy(dtype=float))
    xm, xs = X_log.mean(0), X_log.std(0); xs[xs < 1e-9] = 1
    ym, ys = Y_log.mean(), Y_log.std()

    Xr = np.log10(rows_df[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float))
    z = torch.tensor((Xr - xm) / xs, dtype=torch.float32)
    Gt = torch.tensor(rows_df["G"].to_numpy(), dtype=torch.float32)
    Tt = torch.tensor(rows_df["T"].to_numpy(), dtype=torch.float32)
    Pit = torch.tensor(rows_df["P_in"].to_numpy(), dtype=torch.float32)
    dPt = torch.tensor(rows_df["dP"].to_numpy(), dtype=torch.float32)
    Lct = torch.tensor(rows_df["L_ch"].to_numpy(), dtype=torch.float32)

    models = []
    for k in range(n_ens):
        torch.manual_seed(base_seed + k * 101)
        np.random.seed(base_seed + k * 101)
        m = CFMLP()
        opt = Adam(m.parameters(), lr=1e-3, weight_decay=3e-4)
        sch = torch.optim.lr_scheduler.ReduceLROnPlateau(
            opt, "min", factor=0.5, patience=patience // 4, min_lr=1e-6)
        bl, bs, wt = float("inf"), None, 0
        for ep in range(epochs):
            m.train(); opt.zero_grad()
            out = m(z).squeeze()
            lcf = out * ys + ym
            cf = torch.pow(10.0, torch.clamp(lcf, -2, 6))
            Psq = Pit ** 2 - 2 * R * Tt * cf * Gt ** 2 * Lct
            Po = torch.sqrt(torch.clamp(Psq, min=1e4))
            loss = torch.mean(((Pit - Po - dPt) / dPt) ** 2)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            lv = float(loss.item()); sch.step(lv)
            if lv < bl - 1e-8:
                bl = lv
                bs = {k2: v.clone() for k2, v in m.state_dict().items()}
                wt = 0
            else:
                wt += 1
                if wt >= patience:
                    break
        if bs:
            m.load_state_dict(bs)
        m.eval()
        models.append(m)
        print(f"  ens {k}: {ep + 1} ep, loss={bl:.6f}")

    return models, dict(xm=xm, xs=xs, ym=ym, ys=ys)


def predict_cF(models, norm, L, t, ef):
    x = np.log10([[L, t, ef]])
    z = torch.tensor((x - norm["xm"]) / norm["xs"], dtype=torch.float32)
    s = 0.0
    for m in models:
        with torch.no_grad():
            s += float(m(z).item()) * norm["ys"] + norm["ym"]
    return float(10.0 ** (s / len(models)))


def eval_shanghai(c_F):
    sh_xlsx = _PROJECT / "data" / "raw_data" / "20260401-上海电气天然气加热器实验工况.xlsx"
    sh = pd.read_excel(str(sh_xlsx), engine="openpyxl",
                       sheet_name="Sheet1", header=None, skiprows=2)
    A_FLOW = 36 * 18.0565e-6; L_DOM = 0.231
    err_sq = 0.0; results = []
    for ci in range(16):
        m_air = float(sh.iloc[ci, 5])
        T = float(sh.iloc[ci, 28]) + 273.15
        P_in = P_ATM + float(sh.iloc[ci, 30])
        dP_exp = float(sh.iloc[ci, 30]) - float(sh.iloc[ci, 31])
        G = m_air / A_FLOW
        Psq = P_in ** 2 - 2 * R * T * c_F * G ** 2 * L_DOM
        Po = np.sqrt(max(Psq, 0))
        dP_p = P_in - Po
        err = (dP_p - dP_exp) / dP_exp
        err_sq += err ** 2
        results.append(dict(case=ci+1, dP_exp=dP_exp, dP_pred=dP_p, err_pct=err*100))
    return float(np.sqrt(err_sq / 16) * 100), results


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

    rows_df, ref = load_data()
    print(f"Data: {len(rows_df)} rows, {len(ref)} geometries\n")
    print("Per-geometry c_F:")
    for _, r in ref.iterrows():
        print(f"  L={r.L_mm:.0f} t={r.t_mm:.1f}: c_F={r.c_F:.0f}")

    # Full training
    print("\n--- Full ensemble ---")
    models, norm = train_ensemble(rows_df, ref)

    # In-sample check
    print("\n--- In-sample ---")
    for _, r in ref.iterrows():
        cp = predict_cF(models, norm, r.L_mm, r.t_mm, r.eps_f)
        print(f"  L={r.L_mm:.0f} t={r.t_mm:.1f}: ref={r.c_F:.0f} mlp={cp:.0f} "
              f"({(cp - r.c_F) / r.c_F * 100:+.1f}%)")

    # Shanghai
    g7 = tpms_geometry("Gyroid", 7.0, 0.6, _KS)
    cF_sh = predict_cF(models, norm, 7.0, 0.6, g7["epsilon"] / 2)
    print(f"\nL=7 t=0.6: c_F = {cF_sh:.1f} (optimal=372.7, interp=374)")

    rmsre, results = eval_shanghai(cF_sh)
    print(f"\nShanghai 16 case (c_F={cF_sh:.1f}):")
    print(f"{'C':>2} {'dP_exp':>9} {'dP_pred':>9} {'err%':>8}")
    print("-" * 35)
    for r in results:
        print(f"{r['case']:2d} {r['dP_exp']:9.0f} {r['dP_pred']:9.0f} "
              f"{r['err_pct']:+8.1f}%")
    print(f"\n  Shanghai RMSRE = {rmsre:.2f}%")

    # LOO
    print("\n--- LOO ---")
    loo_mapes = []
    for idx in range(len(ref)):
        r = ref.iloc[idx]
        msk = (rows_df["L_mm"] == r.L_mm) & (rows_df["t_mm"] == r.t_mm)
        tr = rows_df[~msk].reset_index(drop=True)
        te = rows_df[msk].reset_index(drop=True)
        ref_tr = ref[~((ref.L_mm == r.L_mm) & (ref.t_mm == r.t_mm))].reset_index(drop=True)

        ms, nm = train_ensemble(tr, ref_tr, base_seed=SEED + idx * 7,
                                n_ens=3, epochs=4000, patience=400)
        cp = predict_cF(ms, nm, r.L_mm, r.t_mm, r.eps_f)

        tG = te["G"].to_numpy(); tT = te["T"].to_numpy()
        tPi = te["P_in"].to_numpy(); tdP = te["dP"].to_numpy()
        tLc = te["L_ch"].to_numpy()
        Psq = tPi ** 2 - 2 * R * tT * cp * tG ** 2 * tLc
        dPp = tPi - np.sqrt(np.maximum(Psq, 0))
        mape = float(np.mean(np.abs(dPp - tdP) / tdP) * 100)
        loo_mapes.append(mape)
        print(f"  L={r.L_mm:.0f} t={r.t_mm:.1f}: c_F={cp:.0f}, MAPE={mape:.1f}%")

    print(f"\n  Mean LOO MAPE = {np.mean(loo_mapes):.2f}%")
    print(f"\n=== Summary ===")
    print(f"  Shanghai RMSRE = {rmsre:.2f}%")
    print(f"  LOO MAPE = {np.mean(loo_mapes):.2f}%")


if __name__ == "__main__":
    main()
