"""Post-process Shanghai validation xlsx to report dual-side Q errors.

Reads:
  - data/shanghai_validation_aligned.xlsx (sim outputs from validate_shanghai_aligned.py)
  - data/raw_data/20260401-... .xlsx          (Shanghai raw experiment)

Computes Q_air_exp, Q_water_exp from raw experimental T_Aout / T_Bout
and compares against:
  - Q_air_sim  = Q_enthalpy_A  (model predicts T_A_out_mean)
  - Q_water_sim = Q_solid_B    (volume integral h_vB·(Ts-Tb), with frozen Tb)

Notes
-----
Frozen-Tb means model has experimental T_Bin/T_Bout pinned along stream.
Solid steady-state energy balance forces Q_solid_A ≈ Q_solid_B, hence
Q_water_sim ≈ Q_air_sim (modulo numerical residual). Reported anyway as
sanity check vs experimental enthalpy on water side.

dP_water is not given (D-F single-stream model cannot predict water dP).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r'D:\Postgraduate\均质化\SJTU-TPMSHX')
sys.path.insert(0, str(REPO / 'sjtu_tpmshx'))
from solvers.tpms_calc import air_cp, water_cp  # noqa: E402

SIM_PATH = REPO / 'data' / 'shanghai_validation_aligned.xlsx'
RAW_PATH = REPO / 'data' / 'raw_data' / '20260401-上海电气天然气加热器实验工况.xlsx'

sim = pd.read_excel(SIM_PATH, engine='openpyxl')
raw = pd.read_excel(RAW_PATH, sheet_name=0, header=None, skiprows=2,
                    engine='openpyxl')

rows = []
for ci in range(16):
    case = ci + 1
    m_air   = float(raw.iloc[ci, 5])
    m_water = float(raw.iloc[ci, 7])
    T_Ain_C  = float(raw.iloc[ci, 28]); T_Ain_K  = T_Ain_C + 273.15
    T_Aout_C = float(raw.iloc[ci, 29]); T_Aout_K = T_Aout_C + 273.15
    T_Bin_C  = float(raw.iloc[ci, 24]); T_Bin_K  = T_Bin_C + 273.15
    T_Bout_C = float(raw.iloc[ci, 25]); T_Bout_K = T_Bout_C + 273.15

    cp_A_avg = float(air_cp(0.5 * (T_Ain_K + T_Aout_K)))
    cp_B_avg = float(water_cp(0.5 * (T_Bin_K + T_Bout_K)))

    Q_air_exp   = m_air   * cp_A_avg * (T_Ain_K  - T_Aout_K)
    Q_water_exp = m_water * cp_B_avg * (T_Bout_K - T_Bin_K)

    # Air-side Q is independently predicted (model solves T_A_out from T_Ain)
    Q_air_sim = float(sim.iloc[ci]['Q_enthalpy_A'])
    # Water-side: Tb is prescribed (frozen) from experimental T_Bin/T_Bout, so
    # Q_water_sim cannot be independently recovered. Solid steady-state energy
    # balance forces ∫h_vA·(Ta-Ts) = ∫h_vB·(Ts-Tb), i.e. Q_solid_A = Q_solid_B.
    # Hence the model's implicit water-side prediction equals Q_air_sim.
    Q_water_sim = Q_air_sim

    err_air   = (Q_air_sim   - Q_air_exp  ) / Q_air_exp   * 100.0
    err_water = (Q_water_sim - Q_water_exp) / Q_water_exp * 100.0
    imbal_exp = (Q_air_exp - Q_water_exp) / Q_air_exp * 100.0

    rows.append({
        'Case': case,
        'Q_air_exp':   round(Q_air_exp,   1),
        'Q_air_sim':   round(Q_air_sim,   1),
        'err_Q_air%':  round(err_air,     2),
        'Q_water_exp': round(Q_water_exp, 1),
        'Q_water_sim': round(Q_water_sim, 1),
        'err_Q_water%': round(err_water,  2),
        'imbal_exp%':  round(imbal_exp,   2),
    })

out = pd.DataFrame(rows)
print(out.to_string(index=False))
print('=' * 78)
ea = np.asarray(out['err_Q_air%'])
ew = np.asarray(out['err_Q_water%'])
ie = np.asarray(out['imbal_exp%'])
print(f"Q_air   RMSRE = {np.sqrt(np.mean(ea**2)):5.2f}%   "
      f"bias = {np.mean(ea):+6.2f}%   max|err| = {np.max(np.abs(ea)):5.2f}%")
print(f"Q_water RMSRE = {np.sqrt(np.mean(ew**2)):5.2f}%   "
      f"bias = {np.mean(ew):+6.2f}%   max|err| = {np.max(np.abs(ew)):5.2f}%")
print(f"Exp imbalance (Q_air-Q_water)/Q_air: "
      f"mean = {np.mean(ie):+5.2f}%   max|imbal| = {np.max(np.abs(ie)):5.2f}%")

out_path = REPO / 'data' / 'shanghai_q_dual_side.csv'
out.to_csv(out_path, index=False, encoding='utf-8-sig')
print(f'\nSaved: {out_path}')
