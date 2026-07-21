# -*- coding: utf-8 -*-
"""A2-1 instrumented probe (iter 50) — the measurement that closed candidate A2.

Measures the ACTUAL captured massflux target vs physical G = rho(T_in,P_in)*v
on a production-shaped partial-BC case with elevated P_inA (dp/P ~ 9%).
Verdict: ratio 0.9951 (half-cell seeded-profile offset, grid-convergent),
NOT 0.912 (the falsified outlet-datum hypothesis). See
openspec/changes/a2-3d-physical-g/proposal.md for the full evidence chain.
Run: .venv/Scripts/python.exe upgrade/tools/a2_g_capture_probe.py
"""
import os, sys
os.chdir(r'E:\LWH\SJTU-TPMSHX-upgrade')
sys.path.insert(0, r'E:\LWH\SJTU-TPMSHX-upgrade')
import numpy as np
from sjtu_tpmshx.pipelines.run_stack_3d_stages import _build_3d_problem
from sjtu_tpmshx.solvers.tpms_calc import air_density

sys.path.insert(0, os.path.join(r'E:\LWH\SJTU-TPMSHX-upgrade', 'sjtu_tpmshx', 'tests'))
from test_partial_bc_ghost_b import _partial_bc_air_air_cfg
cfg = _partial_bc_air_air_cfg(Nx=10, Ny=8, Nz=6)
cfg['P_inA'] = 201325.0   # elevated inlet: deficit would be ~50% if outlet-datum capture were real
prob = _build_3d_problem(cfg)
sA = prob.sA
# force the capture exactly as solve() does (guard replicated)
if not hasattr(sA, '_massflux_target'):
    sA._massflux_target = (np.asarray(sA.v_inlet_field, dtype=np.float64)
                           * sA.rho_field[:, 0, :]).copy()
rho_phys = air_density(cfg['T_inA'], cfg['P_inA'])
G_phys = float(np.mean(np.asarray(sA.v_inlet_field) * rho_phys))
G_capt = float(np.mean(sA._massflux_target))
print(f"rho passed to solver : {sA.rho:.6f}")
print(f"rho(T_in, P_in)      : {rho_phys:.6f}")
print(f"P_ref_abs (outlet)   : {sA.P_ref_abs:.1f}")
print(f"rho(T_in, P_ref_abs) : {air_density(cfg['T_inA'], sA.P_ref_abs):.6f}")
print(f"G captured / G physical = {G_capt/G_phys:.6f}  (1.0 = physical, no deficit)")
sl = sA.rho_field[:, 0, :]
print(f'rho slab min/max/mean: {sl.min():.6f} / {sl.max():.6f} / {sl.mean():.6f}')
v = np.asarray(sA.v_inlet_field)
print(f'v_inlet min/max/mean : {v.min():.4f} / {v.max():.4f} / {v.mean():.4f}')
mask = v != 0
print(f'masked rho mean (v!=0): {sl[mask].mean():.6f}; ratio on masked = {(v*sl)[mask].sum()/(v[mask].sum()*1.662125):.6f}')
