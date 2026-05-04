"""
Load per-geometry f-Re training data from 试验记录表_整理版.xlsx.

Output DataFrame schema:
    tpms    : 'Diamond' | 'Gyroid'
    L_mm    : unit cell size [mm]
    t_mm    : wall thickness [mm]
    eps     : full porosity ε (from tpms_calc.geometry)
    eps_f   : single-channel porosity ε/2
    r_h_m   : hydraulic radius D_h/2 [m]
    Re      : Reynolds number (Excel column "Re", kept for reference/filtering)
    u_mps   : CFD velocity [m/s] (Excel column 13, 速度)
    dP_Pa   : CFD corrected pressure loss [Pa] (Excel column 47, 修正压损)
    rho     : fluid density [kg/m³] (Excel column 12)
    mu      : fluid dynamic viscosity [Pa·s] (Excel column 9)

Friction factor is intentionally NOT computed — downstream D-F extraction
fits the momentum equation ``dP = (μ/K · u + ρ·c_F · u²) · L_channel``
directly on these raw columns. The 修正压损 column is the single source
of truth for pressure loss.

Only the training Excel is used; Shanghai data is deliberately excluded.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Locate sjtu_tpmshx root for data paths and solvers package
_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent  # .../sjtu_tpmshx
sys.path.insert(0, str(_PROJECT_ROOT))
from solvers.tpms_calc import geometry as tpms_geometry  # noqa: E402

DATA_XLSX = _PROJECT_ROOT.parent / "data" / "raw_data" / "试验记录表_整理版.xlsx"

# Sheet names (GBK 汇总)
_SHEETS = {"Diamond": "Diamond_汇总", "Gyroid": "Gyroid_汇总"}

# Column indices in the sheet (0-based, confirmed from header inspection)
_COL_LABEL = 0   # e.g. 'D_8_03'
_COL_L = 1       # L/mm
_COL_T = 2       # t/mm
_COL_RE = 3      # Re
_COL_MU = 9      # 动力粘度 Pa·s
_COL_RHO = 12    # 密度 kg/m³
_COL_U = 13      # 速度 m/s
_COL_DP_CORR = 47  # 修正压损 — corrected pressure loss (single source of truth)

# Re filter: for L=8 mm geometries only, drop rows with Re < _L8_RE_MIN.
# Rationale: in the L=8 region the low-Re samples live in the transition
# regime where the 2-parameter D-F form f = A/Re + B is systematically off,
# and the report's unconstrained fit for Diamond 8/0.3 + Gyroid 8×{0.3,0.4,0.5}
# gave A < 0. Focusing on Re >= 1600 concentrates the fit on the Forchheimer
# branch where both A and B are well-conditioned.
_L8_RE_MIN = 1600.0

# Default k_s used when calling tpms_calc.geometry() — only affects K_ss, not
# ε or D_h which are the only fields we consume here.
_K_S_DEFAULT = 16.0


def _load_sheet(tpms: str) -> pd.DataFrame:
    """Load one TPMS type sheet from the training Excel and return a tidy frame.

    Header rows (row 0 = labels, row 1 = first group divider) and all group
    divider rows (L column is None) are stripped.
    """
    sheet = _SHEETS[tpms]
    raw = pd.read_excel(
        DATA_XLSX,
        sheet_name=sheet,
        engine="openpyxl",
        header=None,
        skiprows=1,  # skip header row 0
    )

    # Keep only rows with numeric L (filters out group divider rows)
    L_col = pd.to_numeric(raw.iloc[:, _COL_L], errors="coerce")
    mask = L_col.notna()

    df = pd.DataFrame(
        {
            "tpms": tpms,
            "label": raw.iloc[:, _COL_LABEL][mask].astype(str).values,
            "L_mm": L_col[mask].astype(float).values,
            "t_mm": pd.to_numeric(raw.iloc[:, _COL_T], errors="coerce")[mask]
            .astype(float)
            .values,
            "Re": pd.to_numeric(raw.iloc[:, _COL_RE], errors="coerce")[mask]
            .astype(float)
            .values,
            "u_mps": pd.to_numeric(raw.iloc[:, _COL_U], errors="coerce")[mask]
            .astype(float)
            .values,
            "dP_Pa": pd.to_numeric(raw.iloc[:, _COL_DP_CORR], errors="coerce")[mask]
            .astype(float)
            .values,
            "rho": pd.to_numeric(raw.iloc[:, _COL_RHO], errors="coerce")[mask]
            .astype(float)
            .values,
            "mu": pd.to_numeric(raw.iloc[:, _COL_MU], errors="coerce")[mask]
            .astype(float)
            .values,
        }
    )

    # Drop any rows where critical columns failed to parse
    df = df.dropna(subset=["Re", "u_mps", "dP_Pa", "rho", "mu"]).reset_index(drop=True)

    # L=8 mm: drop low-Re rows (see _L8_RE_MIN rationale above)
    n_before = len(df)
    l8_mask = (df["L_mm"] == 8.0) & (df["Re"] < _L8_RE_MIN)
    if l8_mask.any():
        df = df[~l8_mask].reset_index(drop=True)
        print(f"  [{tpms}] dropped {n_before - len(df)} L=8 rows with Re < {_L8_RE_MIN:g}")

    return df


def _attach_geometry(df: pd.DataFrame) -> pd.DataFrame:
    """Add eps, eps_f, r_h_m columns computed from tpms_calc.geometry.

    Geometry is cached per (tpms, L, t) triple so we only pay the voxel
    integration cost once per geometry.
    """
    cache: dict[tuple[str, float, float], tuple[float, float]] = {}

    eps = np.empty(len(df))
    rh = np.empty(len(df))
    for i, row in df.iterrows():
        key = (row["tpms"], float(row["L_mm"]), float(row["t_mm"]))
        if key not in cache:
            g = tpms_geometry(key[0], key[1], key[2], _K_S_DEFAULT)
            cache[key] = (float(g["epsilon"]), float(g["D_h"]) / 2.0)
        e, r = cache[key]
        eps[i] = e
        rh[i] = r

    out = df.copy()
    out["eps"] = eps
    out["eps_f"] = eps / 2.0   # ε_A: per-stream void fraction (sheet HX)
    out["r_h_m"] = rh
    return out[[
        "tpms", "L_mm", "t_mm", "eps", "eps_f", "r_h_m",
        "Re", "u_mps", "dP_Pa", "rho", "mu", "label",
    ]]


def load_all() -> pd.DataFrame:
    """Load and combine Diamond + Gyroid training data with geometry attached."""
    frames = [_attach_geometry(_load_sheet(tpms)) for tpms in _SHEETS]
    return pd.concat(frames, ignore_index=True)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Per-geometry summary: n_points, Re range, mean u / dP, ε, ε_f, r_h."""
    grouped = df.groupby(["tpms", "L_mm", "t_mm"], as_index=False)
    summary = grouped.agg(
        n=("Re", "size"),
        Re_min=("Re", "min"),
        Re_max=("Re", "max"),
        u_mean=("u_mps", "mean"),
        dP_mean=("dP_Pa", "mean"),
        eps=("eps", "first"),
        eps_f=("eps_f", "first"),
        r_h_m=("r_h_m", "first"),
    )
    return summary.sort_values(["tpms", "L_mm", "t_mm"]).reset_index(drop=True)


if __name__ == "__main__":
    # Encoding fix for Windows consoles
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    df = load_all()
    print(f"Loaded {len(df)} rows from {DATA_XLSX.name}")
    print(f"  tpms types : {sorted(df['tpms'].unique())}")
    print(f"  (L, t) geos: {df.groupby('tpms').apply(lambda g: g[['L_mm','t_mm']].drop_duplicates().shape[0]).to_dict()}")
    print()
    print("Per-geometry summary:")
    print(summarize(df).to_string(index=False))
