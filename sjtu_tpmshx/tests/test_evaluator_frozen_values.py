"""Frozen-value regression for the 2D + 3D continuous-field evaluators.

Pins the exact (Q_neg, dP, mass) outputs of ``evaluate_design`` (2D) and
``evaluate_design_3d`` (3D) on fixed decision vectors, captured on master
BEFORE the B3 C7 shared-quantization dedup. C7 moves the per-cell
(L, t) quantization key from Python ``round()`` to ``np.round`` inside the
shared ``solvers.continuous_field.props_from_Lt_fields`` helper; both are
round-half-even and should agree on the 0.05/0.01-quantized grid, but a
key shift of 1e-4 mm would feed different ``tpms_calc.compute`` inputs and
move the result at >=1e-6. This test is the gate that catches exactly
that — the NON-UNIFORM cases exercise the multi-unique-pair scatter path
(a uniform field has cache_size==1 and would not gate the rounding).

rel=1e-12 (not exact ==): same-machine numba is deterministic, but the
tolerance absorbs trailing-ULP float-repr noise while still catching any
rounding-key / ordering change (which moves results far above 1e-12).
Same capture/check convention as runs/_out/_golden_3d.py. If a different
CI machine trips this on FMA/thread-count variance, relax to rel=1e-9.

Marked ``slow`` (each eval is a full SIMPLE x2 + LTNE solve).
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

warnings.filterwarnings('ignore', category=UserWarning)

from solvers.continuous_field import uniform_field
from optimization.evaluator import evaluate_design
from optimization.evaluator_3d import evaluate_design_3d

pytestmark = pytest.mark.slow

_REL = 1e-12

# Lighter solver settings (mirror tests/test_evaluator_sanity.py:_FAST_CFG).
_FAST_CFG = {'max_iter_simple': 800, 'tol_simple': 1e-3,
             'max_iter_energy': 1500, 'tol_energy': 0.5, 'n_rho_loops': 1}

_CFG_3D = {'Nx_3d': 10, 'Ny_3d': 6, 'Nz_3d': 3, 'max_outer_3d': 2,
           'max_iter_energy': 800, 'tol_energy': 0.5}

# Non-uniform 16D decision vector: [L_flat(8), t_flat(8)] (mm), L > t.
# n_ctrl=(4,4) symmetric_y → 8 L + 8 t. Spatially-varying ⇒ many unique
# quantized (L, t) pairs ⇒ exercises the scatter rounding C7 touches.
_X_NONUNIF = np.array([5.0, 6.0, 7.0, 8.0, 5.5, 6.5, 7.5, 6.0,
                       0.40, 0.45, 0.50, 0.55, 0.42, 0.48, 0.52, 0.46])

# ── frozen outputs captured on master pre-C7 (2026-06-13) ──
# 2D Q re-baselined 2026-06-24: the 2D-coupling-stability fix makes fluid B use
# 1st-order convection (no SOU) — needed because the SOU deferred correction
# destabilises the stiff outer coupling at fine grids (water dT_B oscillates).
# Effect is isolated to the energy Q[0] (~0.48% shift, deterministic); dP[1] and
# mass[2] are unchanged. See solvers/ltne_energy.py `_gs_full_chunk` fluid-B block.
#
# 2D re-baselined 2026-06-25: the 2D air solve switched to the MASS-FLUX inlet
# (hold inlet ρ·v constant, SIMPLESolver._apply_massflux_inlet — the 2D port of
# the 3D Bug-B fix, per-cell v_inlet_field[i] = G/ρ[i,0] = "Option A"). It pins
# the physical inlet throughput instead of letting it float with the
# compressible inlet density, fixing the velocity-inlet grid drift (Shanghai 2D
# dP RMSRE 35.8%→8.4%, ≈ 3D). Verified the entire drift here is attributable to
# it: with massflux_inlet=False both tuples reproduce the prior frozen values to
# rel=1e-9. Q[0] and dP[1] move (deterministic); mass[2] (geometry) is unchanged.
# Per-cell (Option A) vs lateral-mean (Option B) differs only at rel≤2e-6 here
# (inlet density near-uniform on a full-face inlet). Old: (-8536.46.., 11140.60..)
# / (-7992.76.., 8246.63..).
#
# 2D Q re-baselined 2026-06-25 (#2): the ENERGY SOU deferred correction is now
# face-consistent — each shared face uses F_face=0.5*(Fx_P+Fx_nbr) so the
# correction telescopes globally instead of injecting spurious energy on the
# compressible (non-uniform-velocity) fluid-A field (audit: 2d-sou-not-
# conservative). ONLY Q[0] moves (the energy field): +0.035% uniform / +0.022%
# nonuniform; dP[1] (SIMPLE pressure) and mass[2] (geometry) are bit-identical.
# Old Q: -8168.931136825195 / -7734.528734545178.
#
# 2D re-baselined 2026-06-28 (N2): the MOMENTUM SOU deferred correction is now
# face-consistent too — each face's minmod limiter is scaled by THAT face's flux
# (Fw west, Fe east; Fs/Fn) so it telescopes instead of using one cell-flux for
# both faces (audit N2, the momentum analog of the 2026-06-25 energy fix). Now
# BOTH Q[0] (energy depends on velocity) AND dP[1] (SIMPLE pressure) move at
# TRUNCATION level (~6e-7 / 2.3e-5 uniform; mass[2] geometry bit-identical). The
# SOU is a minmod-limited high-order correction sub-dominant to the Forchheimer
# drag, so Shanghai 2D validation is UNCHANGED (RMSRE_dP 8.35% / Q 2.51%).
# Old: (-8171.756522905283, 10057.99677021549) / (-7736.238110417324, 7584.5716386808235).
# re-baselined 2026-06-30: gamma_df K moved from the SmoothDF Dh² trend to the
# CFD-refit surface (c_F unchanged). dP[0] and Q[1] move (K shifts the Darcy term
# and, via the velocity field, the h_v coupling); mass[2] (geometry) is unchanged.
# See gamma_df.py K UPDATE note + openspec/changes/df-coeffs-cfd-refit.
#
# 2D NONUNIF re-baselined 2026-07-02 (R1, openspec solver-efficiency-r1-r4):
# SIMPLESolver.solve() gained the 3D-style lowre early-exit (velocity-stability
# gated). The nonuniform eval's SIMPLE solve now exits at the plateau instead of
# burning max_iter_simple, so the frozen iterate shifts at plateau-noise level:
# Q[0] 1.4e-4, dP[1] 6.5e-4 rel; mass[2] (geometry) bit-identical. Deterministic.
# The UNIFORM case reaches the strict residual tol before the early-exit fires
# and is unchanged. Old: (-7724.45529028308, 8027.234654920353).
# re-baselined 2026-07-06 (B2): chi_S switched from the uncalibrated 1.0 to
# the unit-cell homogenization fit chi_s_eff(type, eps) (~0.59-0.83 over the
# production window) — K_ss drops ~35% at typical eps, weakening axial solid
# conduction. Q[0] moves (2D +0.07..0.12%, 3D -0.10..-0.35%); 2D dP[1] and
# all mass[2] are BIT-IDENTICAL (K_ss enters the energy solve only); 3D dP
# shifts ~1e-4 rel via the rho(T) outer coupling. Env TPMSHX_CHI_S=1.0
# reproduces the old tuples. Old: (-8155.898092263062, ...), (-7725.544448374041,
# ...), (-7847.064062565555, 18179.20973508683, ...), (-10066.289384156315,
# 5968.569070037876, ...).
# re-baselined 2026-07-06 (A3): 2D LTNE convection switched to SIGNED
# shared-face fluxes (temperature-form consistent, Patankar; the cell-local
# |u|-magnitude scheme mismatched fluxes across faces on non-uniform
# eps*rho_cp*u fields). ONLY Q[0] moves (2D uniform -0.049%, nonuniform
# -0.034%); dP[1] and mass[2] are BIT-IDENTICAL (energy solve only). 3D
# tuples untouched (3D kernel already conservative). Old Q:
# -8165.653571275229 / -7731.140029573464.
_FROZEN_2D_UNIFORM = (-8161.676768977079, 10661.113158337937,
                      3.446685791015626)
_FROZEN_2D_NONUNIF = (-7728.475410596369, 8022.029234363068,
                      3.6729327392578126)
_FROZEN_3D_UNIFORM = (-7819.313135202607, 18176.77875067786,
                      6.323593139648438)
_FROZEN_3D_NONUNIF = (-10056.123672085494, 5968.430162466379,
                      3.675970458984375)


def _assert_tuple(got, frozen, label):
    assert len(got) == len(frozen), f"{label}: arity {len(got)} != {len(frozen)}"
    for i, (g, fz) in enumerate(zip(got, frozen)):
        assert float(g) == pytest.approx(fz, rel=_REL), (
            f"{label}[{i}] drifted: got {float(g)!r} vs frozen {fz!r}")


def test_frozen_2d_uniform():
    fc = uniform_field(6.0, 0.4, 'Diamond', 17.0, L_domain=0.10, H_domain=0.05)
    got = evaluate_design(x=None, cfg=dict(_FAST_CFG), fc=fc)
    _assert_tuple(got, _FROZEN_2D_UNIFORM, '2D-uniform')


def test_frozen_2d_nonuniform():
    got = evaluate_design(x=_X_NONUNIF.copy(), cfg=dict(_FAST_CFG))
    _assert_tuple(got, _FROZEN_2D_NONUNIF, '2D-nonuniform')


def test_frozen_3d_uniform():
    x_u = np.concatenate([np.full(8, 4.0), np.full(8, 0.6)])
    got = evaluate_design_3d(x_u, dict(_CFG_3D))
    _assert_tuple(got, _FROZEN_3D_UNIFORM, '3D-uniform')


def test_frozen_3d_nonuniform():
    got = evaluate_design_3d(_X_NONUNIF.copy(), dict(_CFG_3D))
    _assert_tuple(got, _FROZEN_3D_NONUNIF, '3D-nonuniform')
