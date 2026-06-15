"""ingest_cfd_kappa.py — turn external ANSYS Fluent per-side runs into κ tables.

Reads a Fluent results CSV (one row per design point per side) with columns:

    tpms, L_mm, t_mm, eps_side, eps_sym, K_cfd, cF_cfd

computes the **relative-ratio** correction against the existing symmetric
Darcy-Forchheimer baseline:

    κ_K(r)  = K_cfd  / K_sym ,    κ_cF(r) = cF_cfd / cF_sym ,    r = ε_side/ε_sym

where (K_sym, cF_sym) = ``predict.predict_K_cF(tpms, L, t, ε_sym)`` (the κ=1
symmetric anchor). The ratio cancels the shared CFD provenance (mesh /
turbulence model / AM-roughness factor) so only the geometry-induced per-side
shift survives. Fits a monotone κ_K(r), κ_cF(r) map (linear interp on sorted r,
flat-extrapolated, with the r=1→κ=1 anchor enforced) and registers it via
``kappa_asym.set_kappa_table``. After ingest, set env ``TPMSHX_ASYM_KAPPA=1``
to activate the correction in the 3D stack.

Usage:  python -m df_surrogate.ingest_cfd_kappa results.csv
        (or import ingest(path) programmatically)
"""
from __future__ import annotations

import csv
import sys

import numpy as np

from df_surrogate.predict import predict_K_cF
from df_surrogate import kappa_asym


def _monotone_interp(r_pts, k_pts):
    """Return a callable κ(r): linear interp on sorted (r, κ), flat ends,
    with the r=1 → κ=1 anchor guaranteed present."""
    r = list(r_pts)
    k = list(k_pts)
    if not any(abs(rv - 1.0) < 1e-9 for rv in r):
        r.append(1.0)
        k.append(1.0)
    order = np.argsort(r)
    r_s = np.asarray(r, dtype=np.float64)[order]
    k_s = np.asarray(k, dtype=np.float64)[order]
    # de-duplicate identical r (np.interp needs strictly increasing x)
    keep = np.concatenate(([True], np.diff(r_s) > 1e-12))
    r_s, k_s = r_s[keep], k_s[keep]
    return lambda rq: float(np.interp(rq, r_s, k_s))   # flat beyond ends


def ingest(path: str) -> dict:
    """Read Fluent results CSV → fit + register κ tables. Returns a summary
    dict {tpms: n_points}."""
    by_tpms: dict = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tpms = row["tpms"].strip()
            L = float(row["L_mm"]); t = float(row["t_mm"])
            eps_side = float(row["eps_side"]); eps_sym = float(row["eps_sym"])
            K_cfd = float(row["K_cfd"]); cF_cfd = float(row["cF_cfd"])
            K_sym, cF_sym = predict_K_cF(tpms, L, t, eps_sym)
            r = eps_side / eps_sym if eps_sym > 0 else 1.0
            kK = K_cfd / K_sym if K_sym > 0 else 1.0
            kcF = cF_cfd / cF_sym if cF_sym > 0 else 1.0
            by_tpms.setdefault(tpms, {"r": [], "kK": [], "kcF": []})
            by_tpms[tpms]["r"].append(r)
            by_tpms[tpms]["kK"].append(kK)
            by_tpms[tpms]["kcF"].append(kcF)

    summary = {}
    for tpms, d in by_tpms.items():
        kK_fn = _monotone_interp(d["r"], d["kK"])
        kcF_fn = _monotone_interp(d["r"], d["kcF"])
        kappa_asym.set_kappa_table(tpms, kK_fn, kcF_fn)
        summary[tpms] = len(d["r"])
        print(f"[kappa] {tpms}: {len(d['r'])} points, "
              f"r∈[{min(d['r']):.3f},{max(d['r']):.3f}], "
              f"κ_K∈[{min(d['kK']):.3f},{max(d['kK']):.3f}], "
              f"κ_cF∈[{min(d['kcF']):.3f},{max(d['kcF']):.3f}]")
    print(f"[kappa] registered {len(summary)} tpms tables. "
          f"Set TPMSHX_ASYM_KAPPA=1 to activate in the 3D stack.")
    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m df_surrogate.ingest_cfd_kappa <results.csv>")
        sys.exit(1)
    ingest(sys.argv[1])
