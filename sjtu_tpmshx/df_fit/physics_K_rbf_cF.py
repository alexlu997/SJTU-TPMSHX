"""
physics_K_rbf_cF.py — K from physics formula, c_F from RBF interpolation.

Step 1: Fit K = C * D_h^a * eps^b from L=4/5/6 WLS K values
Step 2: Fix K=K_physics for all geometries, re-fit c_F from residual
Step 3: RBF interpolate c_F, K always from formula
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent
_PROJECT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scipy.interpolate import RBFInterpolator
from solvers.tpms_calc import geometry as tpms_geometry, air_viscosity, P_atm

R = 287.05; K_S_CELLS = 10; P_ATM = P_atm
XLSX = _PROJECT / "data" / "raw_data" / "试验记录表_整理版.xlsx"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

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
    G_all = pd.to_numeric(raw.iloc[:, 48], errors="coerce")[mask].astype(float).values
    dP_raw = pd.to_numeric(raw.iloc[:, 43], errors="coerce")[mask].astype(float).values

    valid = ~(np.isnan(G_all) | np.isnan(dP_raw) | np.isnan(T_C))
    L_mm, t_mm, T_C, G_all, dP_raw = (a[valid] for a in
                                        (L_mm, t_mm, T_C, G_all, dP_raw))
    T_K = T_C + 273.15
    mu_all = np.array([air_viscosity(T) for T in T_K])

    # ============================================================
    # Step 1: 从 L=4/5/6 提取 K, 拟合 K(D_h, eps) 幂律
    # ============================================================
    print("=== Step 1: K 物理公式 (从 L=4/5/6 标定) ===")
    K_data = []
    for L_val in [4, 5, 6]:
        for t_val in sorted(np.unique(t_mm[L_mm == L_val])):
            sel = (L_mm == L_val) & (t_mm == t_val)
            if sel.sum() < 3:
                continue
            key = f"G_{int(L_val)}_{int(t_val * 10):02d}"
            alpha = alpha_map.get(key, 1.0)
            g = tpms_geometry("Gyroid", float(L_val), float(t_val), 16.0)
            L_ch = K_S_CELLS * L_val * 1e-3
            gs = G_all[sel]; mu_s = mu_all[sel]; T_s = T_K[sel]
            dp_s = dP_raw[sel]; P_in = P_ATM + dp_s
            lhs = (P_in ** 2 - P_ATM ** 2) / (2 * R * T_s * L_ch)
            X = np.column_stack([mu_s * gs, gs ** 2])
            w = 1.0 / lhs
            coef, *_ = np.linalg.lstsq(X * w[:, None], lhs * w, rcond=None)
            inv_K_raw = coef[0]
            if inv_K_raw > 0:
                K_corr = (1.0 / inv_K_raw) / alpha
                K_data.append(dict(L=L_val, t=t_val,
                                   D_h=g["D_h"], eps=g["epsilon"], K=K_corr))

    K_df = pd.DataFrame(K_data)
    # 幂律: log10(K) = a + b*log10(D_h) + c*log10(eps)
    Xk = np.column_stack([np.ones(len(K_df)),
                           np.log10(K_df["D_h"].values),
                           np.log10(K_df["eps"].values)])
    yk = np.log10(K_df["K"].values)
    ck, *_ = np.linalg.lstsq(Xk, yk, rcond=None)

    print(f"  K = 10^{ck[0]:.3f} * D_h^{ck[1]:.3f} * eps^{ck[2]:.3f}")
    print(f"  标定自 {len(K_df)} 个几何 (L=4/5/6)")

    def K_physics(D_h, eps):
        return 10.0 ** (ck[0] + ck[1] * np.log10(D_h) + ck[2] * np.log10(eps))

    print(f"\n  验证:")
    for _, r in K_df.iterrows():
        Kp = K_physics(r.D_h, r.eps)
        print(f"    L={r.L:.0f} t={r.t:.1f}: K_wls={r.K:.3e} K_ph={Kp:.3e} "
              f"({(Kp - r.K) / r.K * 100:+.1f}%)")

    # ============================================================
    # Step 2: 固定 K_physics, 拟合 c_F
    # ============================================================
    print(f"\n=== Step 2: 固定 K_physics, 拟合 c_F ===")
    ref_list = []
    rows_list = []
    for L_val in sorted(np.unique(L_mm)):
        for t_val in sorted(np.unique(t_mm[L_mm == L_val])):
            sel = (L_mm == L_val) & (t_mm == t_val)
            if sel.sum() < 3:
                continue
            key = f"G_{int(L_val)}_{int(t_val * 10):02d}"
            alpha = alpha_map.get(key, 1.0)
            g = tpms_geometry("Gyroid", float(L_val), float(t_val), 16.0)
            L_ch = K_S_CELLS * L_val * 1e-3
            K_ph = K_physics(g["D_h"], g["epsilon"])

            gs = G_all[sel]; mu_s = mu_all[sel]; T_s = T_K[sel]
            dp_s = dP_raw[sel]; P_in = P_ATM + dp_s
            lhs = (P_in ** 2 - P_ATM ** 2) / (2 * R * T_s * L_ch)

            # lhs = mu*G/K_ph + c_F_raw * G²
            # => c_F_raw * G² = lhs - mu*G/K_ph
            residual = lhs - mu_s * gs / K_ph
            w = 1.0 / lhs
            cF_raw = float(np.linalg.lstsq(
                (gs ** 2 * w).reshape(-1, 1), residual * w, rcond=None)[0][0])
            cF_corr = alpha * max(cF_raw, 0)

            ref_list.append(dict(
                L_mm=float(L_val), t_mm=float(t_val),
                eps_f=g["epsilon"] / 2, r_h_m=g["D_h"] / 2,
                K=K_ph, c_F=max(cF_corr, 1.0)))

            for i in np.where(sel)[0]:
                dp_corr = dP_raw[i] * alpha
                rows_list.append(dict(
                    L_mm=L_mm[i], t_mm=t_mm[i], eps_f=g["epsilon"] / 2,
                    G=G_all[i], mu=mu_all[i], T=T_K[i],
                    P_in=P_ATM + dp_corr, dP=dp_corr,
                    L_ch=K_S_CELLS * L_mm[i] * 1e-3))

    ref = pd.DataFrame(ref_list)
    rows_df = pd.DataFrame(rows_list)

    print(f"\n{'L':>3} {'t':>4} {'K_ph':>10} {'c_F':>8}")
    print("-" * 28)
    for _, r in ref.iterrows():
        print(f"{r.L_mm:3.0f} {r.t_mm:4.1f} {r.K:10.3e} {r.c_F:8.1f}")

    # ============================================================
    # Step 3: RBF c_F + K_physics → 预测
    # ============================================================
    X_feat = ref[["L_mm", "t_mm", "eps_f"]].to_numpy(dtype=float)
    log_cF = np.log10(ref["c_F"].to_numpy())
    rbf_cF = RBFInterpolator(X_feat, log_cF,
                              kernel="thin_plate_spline", smoothing=0)

    g7 = tpms_geometry("Gyroid", 7.0, 0.6, 16.0)
    K_7 = K_physics(g7["D_h"], g7["epsilon"])
    cF_7 = 10.0 ** rbf_cF(np.array([[7.0, 0.6, g7["epsilon"] / 2]]))[0]

    print(f"\n=== L=7 t=0.6 预测 ===")
    print(f"  K = {K_7:.4e} (物理公式)")
    print(f"  c_F = {cF_7:.2f} (RBF)")
    print(f"  (逆拟合最优: K=inf, c_F=372.7)")

    mu7 = air_viscosity(399.2); G7 = 3.50
    d7 = mu7 * G7 / K_7; f7 = cF_7 * G7 ** 2
    print(f"  Case 1 Darcy 占比: {d7 / (d7 + f7) * 100:.1f}%")

    # Shanghai
    sh_xlsx = _PROJECT / "data" / "raw_data" / \
              "20260401-上海电气天然气加热器实验工况.xlsx"
    sh = pd.read_excel(str(sh_xlsx), engine="openpyxl",
                       sheet_name="Sheet1", header=None, skiprows=2)
    A_FLOW = 36 * 18.0565e-6; L_DOM = 0.231

    print(f"\n{'C':>2} {'dP_exp':>9} {'dP_pred':>9} {'err%':>8} {'Darcy%':>7}")
    print("-" * 42)
    err_sq = 0
    for ci in range(16):
        m = float(sh.iloc[ci, 5]); T = float(sh.iloc[ci, 28]) + 273.15
        P_in = P_ATM + float(sh.iloc[ci, 30])
        dP_exp = float(sh.iloc[ci, 30]) - float(sh.iloc[ci, 31])
        G = m / A_FLOW; mu = air_viscosity(T)
        darcy = mu * G / K_7; forch = cF_7 * G ** 2
        C = darcy + forch
        Psq = P_in ** 2 - 2 * R * T * C * L_DOM
        dPp = P_in - np.sqrt(max(Psq, 0))
        err = (dPp - dP_exp) / dP_exp * 100
        err_sq += (err / 100) ** 2
        dpct = darcy / (darcy + forch) * 100
        print(f"{ci + 1:2d} {dP_exp:9.0f} {dPp:9.0f} {err:+8.1f}% {dpct:6.1f}%")
    rmsre = np.sqrt(err_sq / 16) * 100
    print(f"\n  Shanghai RMSRE = {rmsre:.2f}%")

    # LOO
    print(f"\n=== LOO ===")
    loo_mapes = []
    for idx in range(len(ref)):
        r = ref.iloc[idx]
        mask = np.ones(len(ref), dtype=bool); mask[idx] = False
        rbf_i = RBFInterpolator(X_feat[mask], log_cF[mask],
                                 kernel="thin_plate_spline", smoothing=0)
        cF_p = 10.0 ** rbf_i(X_feat[idx:idx + 1])[0]
        K_p = r.K  # always from physics formula

        grp = rows_df[(rows_df["L_mm"] == r.L_mm) &
                       (rows_df["t_mm"] == r.t_mm)]
        Gt = grp["G"].to_numpy(); Tt = grp["T"].to_numpy()
        mut = grp["mu"].to_numpy()
        Pit = grp["P_in"].to_numpy(); dPt = grp["dP"].to_numpy()
        Lct = grp["L_ch"].to_numpy()
        C = mut * Gt / K_p + cF_p * Gt ** 2
        Psq = Pit ** 2 - 2 * R * Tt * C * Lct
        dPp = Pit - np.sqrt(np.maximum(Psq, 0))
        mape = float(np.mean(np.abs(dPp - dPt) / dPt) * 100)
        loo_mapes.append(mape)
        print(f"  L={r.L_mm:.0f} t={r.t_mm:.1f}: cF={cF_p:.0f} "
              f"MAPE={mape:.1f}%")

    print(f"\n  Mean LOO MAPE = {np.mean(loo_mapes):.2f}%")
    print(f"\n=== Summary ===")
    print(f"  Shanghai RMSRE = {rmsre:.2f}%")
    print(f"  LOO MAPE = {np.mean(loo_mapes):.2f}%")


if __name__ == "__main__":
    main()
