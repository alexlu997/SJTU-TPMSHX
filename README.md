# SJTU-TPMSHX

A research code for **Triply Periodic Minimal Surface (TPMS) heat-exchanger**
analysis: 2D/3D porous-media CFD with LTNE energy, dual-Nu air/water
correlations, and a ε-NTU lumped solver. Validated against the Shanghai
16-case experimental dataset.

> **Status**: research / dissertation code. APIs evolve; expect rough edges.
> **Repo**: <https://github.com/alexlu997/SJTU-TPMSHX>

---

## What it does

| Layer | Capability |
|-------|------------|
| **Geometry** | Diamond + Gyroid TPMS sheet HX, parameterised by cell size `a` and wall thickness `t` |
| **Closures** | Darcy–Forchheimer surrogate (RBF over CFD micro-runs); dual Nusselt (air-side v4.1 ×1.28 / water-side Yan 2024) |
| **2D solver** | SIMPLE Patankar, ideal-gas air, Brinkman–Forchheimer porous core |
| **3D solver** | full SIMPLE 3D **+** Streamfunction–Pressure formulation with 3D Pressure-Poisson (Helmholtz machine-eps mass conservation) |
| **Lumped** | ε-NTU dual-Nu cross-flow, `validate_shanghai_lumped_dual_nu.py` |
| **Validation** | Shanghai 16-case (Q air RMSRE **1.71 %** lumped, **44.66 %** 3D dP) |
| **V&V** | ASME V&V 20 Standard Tier — MMS code verification (p_obs ≈ 1.97), GCI grid convergence, tolerance sweep |
| **GUI** | PySide6 + pyvistaqt 3D viewer, 3-workspace session persistence, glassmorphism dark theme |

---

## Install

Tested: **Python 3.11 / 3.12, Windows 11**. Linux should work; macOS untested.

```bash
git clone https://github.com/alexlu997/SJTU-TPMSHX.git
cd SJTU-TPMSHX
python -m venv .venv
.venv\Scripts\activate         # PowerShell
# source .venv/bin/activate    # bash
pip install -r requirements.txt
```

GPU PyTorch is optional (only needed if you re-train the D-F surrogate); the
runtime path uses an exported joblib RBF model.

---

## Run

### GUI

```bash
python -m sjtu_tpmshx.main
```

### Headless validation (Shanghai 16-case)

```bash
# Lumped ε-NTU dual-Nu — current paper baseline
python sjtu_tpmshx/validation/validate_shanghai_lumped_dual_nu.py

# 3D real solver (SIMPLE, Nz=10)
python sjtu_tpmshx/validation/validate_shanghai_3d_real.py

# 3-path 3D comparison: SIMPLE vs SF-axial vs SF-Poisson
python sjtu_tpmshx/validation/validate_shanghai_3d_pp_compare.py
```

### Tests

```bash
pytest sjtu_tpmshx/tests/ -v
```

---

## Repo layout

```
sjtu_tpmshx/
├── solvers/                     # SIMPLE 2D/3D, streamfunction-pressure, PPE, tpms_calc
├── controllers/                 # Qt: ComputeOrchestrator, ResultCache, SessionManager
├── ui/                          # PySide6 widgets, themes, ui_builders
├── df_fit/                      # Darcy-Forchheimer RBF surrogate fitting
├── optimization/                # NSGA-II Pareto (2D)
├── validation/                  # Shanghai-case scripts (+ legacy/ archive)
├── tests/                       # pytest suite (24 files)
├── examples/, benchmarks/, poc/ # exploratory
└── main.py                      # GUI entrypoint
```

Reports + experiment notes live in **`vault/`** (research notebook, see
`vault/reports/README.md` for the index of 38 reports across 6 sub-topics).

---

## V&V

Standard Tier complete (ASME V&V 20, single-day closure 2026-05-04):

| Phase | Result |
|-------|--------|
| **A — MMS code verification** | Phase A.1–A.4, 5-grid h-refinement, p_obs ≥ 2.07 (gate ≥ 1.5) |
| **B — Grid convergence (GCI)** | T2 0.86 %, T4 H=8 grid 30 1.37 % |
| **C — Tolerance / iteration sweep** | spread 0.02 % |
| **D — Domain sweep** | 18 / 20 PASS, applicability `u ≤ 10 m/s` |
| **E — Validation vs experiment** | Shanghai lumped Q RMSRE 1.71 % |

For Streamfunction–Pressure formulation: 3D PPE Phase A MMS p_obs = 1.975
(SOU 2nd-order verified).

---

## Cite

If you use this code, please cite the dissertation (in preparation).
Provisional BibTeX:

```bibtex
@misc{lu_sjtu_tpmshx_2026,
  author = {Lu, Alex},
  title  = {SJTU-TPMSHX: a Validated Solver for TPMS Heat Exchangers},
  year   = {2026},
  url    = {https://github.com/alexlu997/SJTU-TPMSHX},
}
```

---

## Licence

MIT — see [LICENSE](LICENSE).
