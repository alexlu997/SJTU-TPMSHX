"""pipelines/stages_2d.py — 2D compute stage functions for SJTU-TPMSHX.

The cfg-only stage functions consumed by
controllers.compute_pipeline.Pipeline2D (_parse_inputs_cfg →
_build_fields_cfg → _run_solvers_cfg → _finalize_cfg).  Compute-only
(Qt/matplotlib-free); 2D result rendering lives in
``ui/plot_2d_results.py``.

Moved out of `runs/run_calculation.py` in batch-3 (2026-06-13) — completing
the controllers→runs layer-inversion fix.  This module imports nothing from
`runs/` or `controllers/` (contracts-layer split 2026-07-02: ComputeConfig /
ComputeResult now come from `domain`, so the old pipelines↔controllers cycle
— and the deferred imports that held it shut — is gone).

Originally extracted from main.py (Task B.9). C3 audit (2026-05-28, L-a-1):
scalar UI inputs route through ``ui.window_config.config_from_window`` rather
than direct ``le_*`` widget reads; the window is still required for non-le
state (zone config, _eps_A, extrap reasons, _temp_to_K hook, _DIR_MAP).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import os

import numpy as np
from sjtu_tpmshx.domain.compute_config import ComputeConfig, bc_to_dict
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.solvers.tpms_calc import compute as tpms_compute, geometry as tpms_geometry
from sjtu_tpmshx.solvers.df_projection import override_simple_K_cF, extract_dP_from_simple
from sjtu_tpmshx.pipelines._stage_common import (
    validate_domain_dims, surrogate_extrap_reasons, safe_float,
    geometry_props,
)
from sjtu_tpmshx.logutil import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

# Re-exports — external consumers (controllers/compute_pipeline, tests)
# import these from pipelines.stages_2d; keep every moved name reachable.
from sjtu_tpmshx.pipelines.solve_2d import (
    _enthalpy_balance_2d, _PipelineWindowShim, _compute_pressure_2d,
    _apply_zone_stats_2d, _compute_Q_richardson, _run_solvers,
)

_log = get_logger(__name__)


# B2 2.1b (2026-06-13): the legacy window entrypoints
# run_calculation_inner / run_calculation_inner_cfg and the
# _parse_inputs window adapter were DELETED — the GUI 2D path now drives
# controllers.compute_pipeline.Pipeline2D (cfg-only stage functions
# below) and copies the ComputeResult back via Main_Menu.write_result.


def _check_zoned_fluid_support(compute_cfg: ComputeConfig) -> None:
    """Guard: the 2D zone property builders (ZoneConfig.compute_properties /
    build_grid_arrays and sigmoid_field.build_continuous_arrays) hardcode AIR
    (they call tpms_calc.compute / air_* with no fluid_type), so a water side
    would silently get air Nu/k — h_v ~280x and K_ff ~25x off (audit:
    zoned-water-side-uses-air-properties). Raise until per-fluid zoned props
    are implemented; the error propagates without solving another problem. The 3D
    zoned path threads fluid_type_B and is unaffected.
    """
    if not getattr(compute_cfg.zones, 'enabled', False):
        return
    fA = compute_cfg.fluid_A.type
    fB = compute_cfg.fluid_B.type
    if fA != 'air' or fB != 'air':
        raise NotImplementedError(
            f"Zoned 2D compute supports air only (fluid_A={fA!r}, "
            f"fluid_B={fB!r}); the zone property builders would silently use "
            "air properties for a non-air side. Disable zones or run a uniform "
            "(non-zoned) case for water.")


def _parse_inputs_cfg(compute_cfg: ComputeConfig) -> dict[str, Any]:
    """Phase 1 (Qt-free): assemble the parsed-config dict from a
    :class:`ComputeConfig`.

    Audit C4 (L-a-2): cfg-only mirror of ``_parse_inputs``. The legacy
    function now wraps this and propagates ``extrap_reasons`` back onto
    ``window._extrap_reasons`` so the UI watermark keeps working.

    Returns the same parsed dict as ``_parse_inputs`` plus an
    ``extrap_reasons`` key (the legacy version mutated this onto the
    window directly; the cfg-pure version returns it instead).
    """
    warnings_list = []
    extrap_reasons = []

    # Block unsupported fluids up-front (2D path currently hardcodes air_*
    # 2026-05-09 (option B) — water + air supported in 2D Compute. sCO2
    # still blocks. Per-side fluid type captured into cfg so _run_solvers
    # picks the right property accessors.
    from sjtu_tpmshx.solvers.tpms_calc import validate_fluid_type
    fluid_A = compute_cfg.fluid_A.type
    fluid_B = compute_cfg.fluid_B.type
    validate_fluid_type(fluid_A, 'A')
    validate_fluid_type(fluid_B, 'B')

    # Surrogate training-domain guard for the UI Compute path (#10) —
    # previously only the optimizer did this; the Compute tab now also
    # guards a single out-of-window (u, T, L, t) from silent RBF extrap.
    # If ``cfg.extrap.allow`` is set (the checkbox is on, or the env
    # var TPMSHX_ALLOW_EXTRAP=1 fed the dataclass), out-of-window
    # values downgrade to warn and we stash the reasons in the parsed
    # dict so the UI can mark the result + watermark the plots.
    _allow_extrap = bool(compute_cfg.extrap.allow)
    extrap_reasons += surrogate_extrap_reasons(compute_cfg, _allow_extrap)

    # Scalar parameters (already cfg-sourced).
    L = compute_cfg.geometry.L_dom_m
    H = compute_cfg.geometry.H_dom_m
    N_x = compute_cfg.solver.Nx
    N_y = compute_cfg.solver.Ny
    u_A = compute_cfg.fluid_A.u_mps
    u_B = compute_cfg.fluid_B.u_mps
    T_inA = compute_cfg.fluid_A.T_in_K
    T_inB = compute_cfg.fluid_B.T_in_K

    # Optional solid initial temperature — None means legacy seed
    # 0.5*(T_inA+T_inB) inside solve_full_domain. Not a prescribed Ts.
    T_s_init = compute_cfg.solver.T_s_init_K

    # Defensive unit firewall — shared with the 3D parse (_stage_common).
    validate_domain_dims([('L', L), ('H', H)])

    dx = L / N_x
    dy = H / N_y
    cfgA = bc_to_dict(compute_cfg.bc_A, L, H, side='A')
    cfgB = bc_to_dict(compute_cfg.bc_B, L, H, side='A')
    dir_A = cfgA['dir']
    dir_B = cfgB['dir']

    # TPMS geometry derives porosity + hydraulic radius purely from cfg.
    # The legacy version cached this in ``window._eps_A``; we re-derive
    # because tpms_geometry is cheap (closed-form per Cheng 2021).
    tpms_type = compute_cfg.geometry.tpms
    Lcell = compute_cfg.geometry.L_cell_mm
    t_wall = compute_cfg.geometry.t_wall_mm
    k_s = compute_cfg.geometry.k_s_W_mK
    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    eps = g['epsilon']
    r_h = g['D_h'] / 2.0

    # ── zone config from cfg.zones (pre-resolved at UI boundary) ──
    zone_config = None
    za = None
    z_axis = 'y'
    if compute_cfg.zones.enabled:
        compute_cfg.zones.validate()
        _check_zoned_fluid_support(compute_cfg)
        z_axis = compute_cfg.zones.axis
        P_in_val = compute_cfg.fluid_A.P_in_Pa
        if z_axis == 'grid':
            grid = compute_cfg.zones.grid
            _x_dec = compute_cfg.zones.pareto_x_decision
            if _x_dec is not None:
                from sjtu_tpmshx.solvers.sigmoid_field import (
                    build_continuous_arrays, get_geometry_lut,
                )
                _lut = get_geometry_lut(tpms_type)
                za = build_continuous_arrays(
                    _x_dec, Lcell, t_wall,
                    compute_cfg.zones.pareto_y_trans_inlet,
                    compute_cfg.zones.pareto_y_trans_outlet,
                    N_x, N_y, L, H,
                    tpms_type, k_s,
                    u_A, u_B, T_inA, T_inB, _lut,
                    P_in=P_in_val,  # FIX (2026-06-24 audit): was defaulting to P_atm
                    allow_extrap=_allow_extrap,
                    fluid_type=fluid_A)  # air-only builder; non-air raises
                _log.info(f"[ZONE] Continuous Sigmoid field ({N_x}x{N_y})")
            else:
                from sjtu_tpmshx.solvers.zone_config import ZoneConfig
                za = ZoneConfig.build_grid_arrays(
                    N_x, N_y, L, H,
                    grid['cells'],
                    grid['tpms_type'], grid['k_s'],
                    u_A, u_B, T_inA, T_inB, P_in_val)
                _log.info(f"[ZONE] Grid {len(grid['cells'])} cells (discrete)")
            zone_config = 'grid'
        else:
            # The UI supplies an object; canonical JSON retains its data shape.
            if compute_cfg.zones.config is None:
                raise ValueError('Enabled 1D zones require a ZoneConfig')
            zone_config = compute_cfg.zones.config
            if isinstance(zone_config, dict):
                from copy import deepcopy
                from sjtu_tpmshx.solvers.zone_config import Zone, ZoneConfig

                zone_data = deepcopy(zone_config)
                zone_data['zones'] = [Zone(**zone) for zone in zone_data['zones']]
                zone_config = ZoneConfig(**zone_data)
            zone_config.compute_properties(
                u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
                P_in=P_in_val)
            z_dim = H if z_axis == 'y' else L
            za = zone_config.build_structured_arrays(
                N_x, N_y, z_dim, axis=z_axis)
            _log.info(f"[ZONE] {len(zone_config.zones)} zones along "
                      f"{z_axis}")

    # Smooth zone property arrays at boundaries (skip continuous mode).
    if za is not None and zone_config is not None and za.get('axis') != 'continuous':
        from scipy.ndimage import gaussian_filter
        _sigma = 2.0
        for _key in ('K_ffA_arr', 'K_ffB_arr', 'K_ss_arr',
                     'h_vA_arr', 'h_vB_arr', 'eps_arr'):
            if _key in za:
                za[_key] = gaussian_filter(za[_key], sigma=_sigma)

    return {
        'L': L, 'H': H,
        'N_x': N_x, 'N_y': N_y,
        'dx': dx, 'dy': dy,
        'u_A': u_A, 'u_B': u_B,
        'T_inA': T_inA, 'T_inB': T_inB,
        'T_s_init': T_s_init,
        'cfgA': cfgA, 'cfgB': cfgB,
        'dir_A': dir_A, 'dir_B': dir_B,
        'envelope_mode': getattr(compute_cfg, 'envelope_mode', 'raise'),
        'tpms_type': tpms_type,
        'Lcell': Lcell, 't_wall': t_wall, 'k_s': k_s,
        'eps': eps, 'r_h': r_h,
        'zone_config': zone_config, 'za': za, 'z_axis': z_axis,
        'fluid_A': fluid_A, 'fluid_B': fluid_B,
        'warnings_list': warnings_list,
        'extrap_reasons': extrap_reasons,
        # Stash the strict ComputeConfig so downstream phases
        # (_build_fields / _run_solvers / _store_results) can reach
        # P_inA / P_inB etc. without re-reading ``le_*`` widget.
        'compute_cfg': compute_cfg,
    }


def _build_fields_cfg(cfg: dict[str, Any], *,
                      live_residuals: dict | None = None) -> dict[str, Any]:
    """Phase 2 (Qt-free): construct aligned grid arrays and SIMPLE
    helper closures.

    Audit C4 (L-a-2): renamed from ``_build_fields(window, cfg)``. The
    two window touches were:

    1. ``window._is_x_dir(d)`` — inlined as ``d in (0, 1)`` per the
       original ``Main_Menu._is_x_dir`` body.
    2. ``window._live_residuals`` (UI sparkline buffer) — now passed
       explicitly via the ``live_residuals`` keyword.  Pipeline2D
       leaves it at ``None`` (no UI); the legacy UI adapter
       :func:`_build_fields` extracts it from the window.
    """
    L = cfg['L']; H = cfg['H']
    N_x = cfg['N_x']; N_y = cfg['N_y']
    cfgA = cfg['cfgA']; cfgB = cfg['cfgB']
    tpms_type = cfg['tpms_type']
    Lcell = cfg['Lcell']; t_wall = cfg['t_wall']; k_s = cfg['k_s']
    eps = cfg['eps']; r_h = cfg['r_h']
    zone_config = cfg['zone_config']; za = cfg['za']

    # ── Step 1: SIMPLE velocity fields on full L × H ──
    def _build_zone_arrays_for_simple(za_dict, N_flow, N_perp, is_x_flow, mu_fluid):
        """Build 1D per-row arrays for SIMPLE from 2D zone arrays.
        SIMPLE's y-axis = flow direction. Need per-row porous params."""
        from sjtu_tpmshx.solvers import tpms_calc as _tc
        mu_eff = np.empty(N_flow, dtype=np.float64)
        r_h_a  = np.empty(N_flow, dtype=np.float64)
        ln_eps = np.empty(N_flow, dtype=np.float64)
        ln_tL  = np.empty(N_flow, dtype=np.float64)
        ln_XSa = np.empty(N_flow, dtype=np.float64)
        for j in range(N_flow):
            # Find matching grid cell for representative L/t
            gc = za_dict.get('grid_cells', za_dict.get('zone_params', []))
            if gc:
                # Use the cell that covers this row's midpoint
                frac = (j + 0.5) / N_flow
                matched = None
                for c in gc:
                    if isinstance(c, dict):
                        if is_x_flow:
                            if c.get('x0', c.get('y_frac_start', 0)) <= frac < c.get('x1', c.get('y_frac_end', 1)):
                                matched = c; break
                        else:
                            if c.get('y0', c.get('y_frac_start', 0)) <= frac < c.get('y1', c.get('y_frac_end', 1)):
                                matched = c; break
                if matched:
                    L_mm = matched.get('L', matched.get('L_mm', Lcell))
                    t_mm = matched.get('t', matched.get('t_mm', t_wall))
                else:
                    L_mm, t_mm = Lcell, t_wall
            else:
                L_mm, t_mm = Lcell, t_wall
            g_loc = tpms_geometry(tpms_type, L_mm, t_mm, k_s)
            e_loc = g_loc['epsilon']
            rh_loc = g_loc['D_h'] / 2.0
            mu_eff[j] = mu_fluid / e_loc
            r_h_a[j] = rh_loc
            ln_eps[j] = np.log(e_loc / 2.0)  # single-channel porosity for f-Re
            ln_tL[j] = np.log(t_mm / L_mm)
            X_mm = 2.0 * rh_loc * 1000.0 if tpms_type == 'Diamond' else L_mm
            ln_XSa[j] = np.log(X_mm / (1000.0 * _tc.Sa_mm))
        return {'mu_eff_arr': mu_eff, 'r_h_arr': r_h_a,
                'ln_eps_arr': ln_eps, 'ln_tL_arr': ln_tL, 'ln_XSa_arr': ln_XSa}

    # Build aligned grid arrays for energy solver
    from sjtu_tpmshx.solvers.simple_solver import _aligned_grid
    _x_breaks = set()
    _y_breaks = set()
    for port in (cfgA, cfgB):
        breaks, cross_dim = (_y_breaks, H) if port['dir'] in (0, 1) else (_x_breaks, L)
        for end in ('in', 'out'):
            ctr = port.get(f'{end}_ctr', port['in_ctr'])
            width = port.get(f'{end}_w', port['in_w'])
            lo, hi = ctr - width / 2, ctr + width / 2
            if lo > cross_dim * 0.001:
                breaks.add(lo)
            if hi < cross_dim * 0.999:
                breaks.add(hi)

    # Use 4-wall Brinkman-BL refined grid when inlet/outlet are full-width (no
    # break points). Otherwise, fall back to aligned uniform grid since
    # refinement would conflict with inlet/outlet boundary alignment.
    _wall_refine_gui = (
        len(_x_breaks) == 0 and len(_y_breaks) == 0
        and zone_config is None and za is None
    )
    if _wall_refine_gui:
        from sjtu_tpmshx.solvers.df_projection import build_master_refined_grid
        try:
            energy_dx, energy_dy, N_x, N_y = build_master_refined_grid(
                L, H, N_x, N_y, n_refine=8, first_cell=0.02e-3, growth=1.8)
            _log.info(f"[run_calculation] Wall-refined grid: {N_x}×{N_y} cells (4-wall BL resolved)")
        except ValueError:
            energy_dx = _aligned_grid(N_x, L, list(_x_breaks))
            energy_dy = _aligned_grid(N_y, H, list(_y_breaks))
    else:
        energy_dx = _aligned_grid(N_x, L, list(_x_breaks))
        energy_dy = _aligned_grid(N_y, H, list(_y_breaks))

    # From this point onward the 2D compute path must use the effective grid
    # dimensions implied by energy_dx/energy_dy, not the raw UI values.  The
    # refined-grid path can expand e.g. user Nx=20 to actual Nx=23; keeping the
    # old cfg dimensions made Ta/rho/P fields broadcast as (20, 4) vs (23, 4).
    N_x = int(len(energy_dx))
    N_y = int(len(energy_dy))
    cfg['N_x'] = N_x
    cfg['N_y'] = N_y

    def _resize_zone_arrays_to_effective_grid(za_dict, shape):
        if za_dict is None:
            return

        def _nearest(arr):
            sx, sy = arr.shape
            ix = np.clip(((np.arange(shape[0]) + 0.5) * sx / shape[0]).astype(int),
                         0, sx - 1)
            iy = np.clip(((np.arange(shape[1]) + 0.5) * sy / shape[1]).astype(int),
                         0, sy - 1)
            return arr[np.ix_(ix, iy)]

        def _linear(arr):
            sx, sy = arr.shape
            x_old = (np.arange(sx) + 0.5) / sx
            y_old = (np.arange(sy) + 0.5) / sy
            x_new = (np.arange(shape[0]) + 0.5) / shape[0]
            y_new = (np.arange(shape[1]) + 0.5) / shape[1]
            tmp = np.empty((shape[0], sy), dtype=np.float64)
            for j in range(sy):
                tmp[:, j] = np.interp(x_new, x_old, arr[:, j])
            out = np.empty(shape, dtype=np.float64)
            for i in range(shape[0]):
                out[i, :] = np.interp(y_new, y_old, tmp[i, :])
            return out

        for key, value in list(za_dict.items()):
            arr = np.asarray(value)
            if arr.ndim != 2 or arr.shape == shape:
                continue
            if arr.shape[0] == 0 or arr.shape[1] == 0:
                continue
            if key == 'zone_id' or not np.issubdtype(arr.dtype, np.floating):
                za_dict[key] = _nearest(arr)
            else:
                za_dict[key] = _linear(arr.astype(np.float64, copy=False))

        if 'eps_arr' in za_dict:
            za_dict['eps_f_arr'] = np.asarray(za_dict['eps_arr'],
                                              dtype=np.float64) / 2.0

    _resize_zone_arrays_to_effective_grid(za, (N_x, N_y))

    # Build the _run_simple closure here so it captures all needed locals.
    # It is returned in fields and called by Phase 3.
    simple_warnings = {}

    def _run_simple(cfg_fluid, rho_f, mu_f, T_in_f, u_f, label, P_in_abs=101325.0,
                    T_field_real=None, fluid_type='ideal_gas',
                    p_shoot_prev=None, df_method=None,
                    rho_inlet_ref=None, fluid_name='air', cancel_check=None):
        """Build + solve SIMPLE for one fluid.

        T_field_real : optional 2D array (Nx, Ny) of cell-centered T. When
        supplied (after first outer iter, from LTNE Ta/Tb), propagated to
        SIMPLE.T_field via update_T_field so inner _update_density() uses
        local T (not stale scalar T_in_f). Required for compressible coupling
        consistency across outer iters.

        fluid_type : 'ideal_gas' (default, air) or 'incompressible' (water).
        Controls whether SIMPLE's _update_density runs ρ = P / (R·T) per
        iter or treats ρ as fixed (water). Option B 2026-05-09.

        p_shoot_prev : optional (P_ref_abs_prev, dP_solved_prev) from the
        PREVIOUS outer iteration's converged SIMPLE (this pipeline recreates
        the solver each outer iter). Consumed only when the C8 shooting knob
        is ON and fluid_type is ideal_gas — see the shooting block below.
        """
        d = cfg_fluid['dir']
        is_x = d in (0, 1)  # x-flow = dirs {+x, -x}
        pipe_lo = cfg_fluid['in_ctr'] - cfg_fluid['in_w'] / 2
        pipe_hi = cfg_fluid['in_ctr'] + cfg_fluid['in_w'] / 2
        out_lo = cfg_fluid.get('out_ctr', cfg_fluid['in_ctr']) - cfg_fluid.get('out_w', cfg_fluid['in_w']) / 2
        out_hi = cfg_fluid.get('out_ctr', cfg_fluid['in_ctr']) + cfg_fluid.get('out_w', cfg_fluid['in_w']) / 2

        # Build zone arrays for SIMPLE if zones are active
        z_arr = None
        from sjtu_tpmshx.solvers.zone_config import ZoneConfig
        if za is not None:
            if is_x:
                z_arr = _build_zone_arrays_for_simple(za, N_x, N_y, True, mu_f)
            else:
                z_arr = _build_zone_arrays_for_simple(za, N_y, N_x, False, mu_f)

        zc_simple = zone_config if (not is_x and isinstance(zone_config, ZoneConfig)) else None

        # Transform rho_f / mu_f (either or both may be 2D) to SIMPLE coords.
        def _to_simple_coords(fld):
            if np.ndim(fld) != 2:
                return fld
            if is_x:
                out = fld.T.copy()
                if d == 1:
                    out = out[:, ::-1].copy()
            else:
                out = fld.copy()
                if d == 3:
                    out = out[:, ::-1].copy()
            return out
        rho_simple = _to_simple_coords(rho_f)
        mu_simple = _to_simple_coords(mu_f)

        # Mass-flux inlet reference density ρ(T_in, P_in): the physical inlet
        # density the pipeline used to convert ṁ → u_f. Passed explicitly so the
        # pin holds the PHYSICAL throughput even though this pipeline recreates
        # the solver every outer iter with an already-compressed rho_f (a
        # field-based capture would ratchet here). sCO2 passes its CoolProp
        # inlet density explicitly; water leaves this unset.
        if rho_inlet_ref is None and fluid_type == 'ideal_gas':
            rho_inlet_ref = float(P_in_abs) / (287.05 * float(T_in_f))

        # ── P_ref_abs is the OUTLET absolute pressure, not the inlet ────────
        # BUG FIX 2026-07-12 (ledger C8). This used to pass `P_ref_abs=P_in_abs`.
        #
        # `P_ref_abs` is the ABSOLUTE pressure the solver's GAUGE field is
        # measured from, and the gauge field's zero sits at the OUTLET: the pp
        # equation pins the outlet row `Pp = 0` (`_kernels_simple_2d.py:735`) and
        # `_correct_jit` never corrects those cells' P, so the outlet gauge stays
        # 0 for the entire solve. Hence
        #
        #       outlet absolute pressure  ==  P_ref_abs   (exactly)
        #       inlet  absolute pressure  ==  P_ref_abs + Δp
        #
        # Passing the INLET pressure therefore anchored the OUTLET at the inlet
        # and floated the whole field up by Δp. Measured on Shanghai case 16
        # (experiment: 304.7 kPa in -> 126.1 kPa out, Δp = 178.7 kPa):
        #
        #       before:  inlet 407.3 kPa -> outlet 304.7 kPa,  Δp =  102.6 kPa
        #                                          ^^^^^ the experiment's INLET
        #
        # The outlet density was ~2.4x too high, so the compressible physics was
        # wrong throughout and Δp came out 43 % low. The error scales with
        # Δp/P_in: negligible for low-Δp designs (case 1: ~1 %), catastrophic for
        # high-Δp ones. It was invisible because the 2D validation gate is
        # kernel-direct and seeds this correctly itself — the gate was validating
        # a path production does not run.
        #
        # (An older project guide described this as "2D is inlet-anchored ... rarely chokes".
        # That was a description of the SYMPTOM, not a design: it "rarely chokes"
        # because it never lets the outlet pressure fall.)
        #
        # 3D always did this right (`run_stack_3d._seed_p_ref`, ~line 620). Use
        # the same 1D compressible Forchheimer closed form, with the SAME (K, cF)
        # the solver itself will build (`simple_solver.py:409-412`), so the seed
        # can never drift from the drag it is seeding for.
        L_stream = float(L if is_x else H)
        _df_mode = getattr(cfg.get('compute_cfg'), 'df_mode', 'cfd_smooth')
        _df_exp = None
        if _df_mode == 'experimental':
            from sjtu_tpmshx.df_surrogate.predict import predict_K_cF as _pred_KcF
            from sjtu_tpmshx.df_surrogate.experimental_correction import apply_correction
            _Kb, _cFb = _pred_KcF(
                tpms_type, float(Lcell), float(t_wall), 0.5 * float(eps),
                method=df_method)
            _df_exp = apply_correction(
                tpms_type, fluid_name, float(Lcell), float(t_wall), _Kb, _cFb,
                u_mps=abs(float(u_f)))
        if fluid_type == 'ideal_gas':
            from sjtu_tpmshx.df_surrogate.predict import predict_K_cF as _pred_KcF
            from sjtu_tpmshx.solvers.envelope import predict_outlet_p_sq
            if _df_exp is None:
                _K0, _cF0 = _pred_KcF(
                    tpms_type, float(Lcell), float(t_wall),
                    0.5 * float(eps), method=df_method)
            else:
                _K0, _cF0 = _df_exp[0], _df_exp[1]
            _rho_in = float(P_in_abs) / (287.05 * float(T_in_f))
            _G = _rho_in * abs(float(u_f))                   # mass flux ρ·u
            _mu_in = float(np.mean(mu_f)) if np.ndim(mu_f) else float(mu_f)
            _C = _mu_in * _G / max(_K0, 1e-16) + _cF0 * _G * _G
            _P_out_sq = predict_outlet_p_sq(float(P_in_abs), float(T_in_f),
                                            _C, L_stream)
            # A non-positive P_out² means the 1D estimate says Δp >= P_in, i.e.
            # the outlet would go to vacuum — no steady solution exists there.
            # The 3D path raises ChokedFlowError; 2D has never had a choke guard
            # (ledger O1), so clip to the same 1e4 Pa floor 3D's `_seed_p_ref`
            # uses and leave the guard as a separate change, rather than silently
            # widening the envelope here.
            P_ref_out = float(np.sqrt(max(_P_out_sq, 1.0e4)))
        else:
            # Incompressible (water, sCO2 Phase-A): ρ is frozen, so the gauge
            # LEVEL does not feed back into the physics at all — only gradients
            # matter. Keep the inlet value (bit-identical to the old behaviour on
            # every water/incompressible solve).
            P_ref_out = float(P_in_abs)

        if is_x:
            s = SIMPLESolver(H, L, N_y, N_x, tpms_type, Lcell, t_wall,
                             eps, r_h, rho_simple, mu_simple, T_in_f,
                             pipe_lo, pipe_hi, u_f,
                             outlet_lo=out_lo, outlet_hi=out_hi,
                             zone_arrays=z_arr,
                             wall_refine=False,
                             P_ref_abs=P_ref_out,
                             rho_inlet_ref=rho_inlet_ref,
                             fluid_type=fluid_type, df_method=df_method)
            # Override grid to match energy solver (SIMPLE x = real y)
            s.dx_arr = energy_dy.copy()
            s.dy_arr = energy_dx.copy()
        else:
            s = SIMPLESolver(L, H, N_x, N_y, tpms_type, Lcell, t_wall,
                             eps, r_h, rho_simple, mu_simple, T_in_f,
                             pipe_lo, pipe_hi, u_f,
                             outlet_lo=out_lo, outlet_hi=out_hi,
                             zone_config=zc_simple,
                             zone_arrays=z_arr if zc_simple is None else None,
                             wall_refine=False,
                             P_ref_abs=P_ref_out,
                             rho_inlet_ref=rho_inlet_ref,
                             fluid_type=fluid_type, df_method=df_method)
            # Override grid to match energy solver (SIMPLE x = real x)
            s.dx_arr = energy_dx.copy()
            s.dy_arr = energy_dy.copy()
        # Same-axis ports can change coordinates without changing cell count.
        # Rebuild the tapered profiles and flux scale on the shared grid.
        s._refresh_ports(pipe_lo, pipe_hi, out_lo, out_hi)
        # Zoned ε push (#2 fix): if zone config gives spatial eps_arr, push to
        # SIMPLE so its continuity uses ∇·(ε·ρ·u)=0 instead of ∇·(ρ·u)=0.
        # Uniform ε leaves default (eps_field=eps everywhere) unchanged.
        if za is not None and za.get('eps_arr') is not None:
            eps_real = np.asarray(za['eps_arr'], dtype=np.float64)
            eps_sol = _to_simple_coords(eps_real)
            if eps_sol.shape == s.eps_field.shape:
                s.eps_field = np.ascontiguousarray(eps_sol, dtype=np.float64)
                # 2026-07-13 audit: refresh the Brinkman μ/ε to the zoned ε.
                # `_mu_eff_field` is built from the SCALAR ε at construction
                # and its only refresh path (`update_T_field`) fires on the
                # first outer T-update, ideal_gas only — so without this the
                # air side's first solve and the water side's WHOLE solve run
                # Brinkman on the uniform ε while continuity runs the zoned ε.
                s._mu_eff_field = np.ascontiguousarray(
                    s.mu_field / s.eps_field, dtype=np.float64)
        # ── Design-specific K/c_F override (2026-04-17) ──
        # zone_config path above already populates per-row K/c_F via
        # predict_K_cF_vec inside SIMPLE.__init__. But zone_arrays path and
        # sigmoid-continuous za don't — SIMPLE falls back to uniform (L0, t0).
        # Here we project the actual design geometry onto SIMPLE's streamwise
        # axis and overwrite _K_arr/_cF_arr so dP reflects the heterogeneous
        # design. See vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §11.
        if za is not None and zc_simple is None:
            Ny_sim = s._K_arr.shape[0]
            fluid = 'A' if is_x else 'B'
            if 'L_field' in za and 't_field' in za:
                override_simple_K_cF(s, tpms_type, k_s, Ny_sim,
                                     None, za['L_field'], za['t_field'], fluid)
            elif za.get('grid_cells'):
                override_simple_K_cF(s, tpms_type, k_s, Ny_sim,
                                     za['grid_cells'], None, None, fluid)
        # Apply the reviewed correction once, after the CFD base is assembled
        # and before pressure re-seeding and SIMPLE.
        if _df_exp is not None:
            _K_applied, _cF_applied, _df_meta = _df_exp
            s._K_arr[:] = _K_applied
            s._cF_arr[:] = _cF_applied
            s._df_metadata = _df_meta
        else:
            from sjtu_tpmshx.df_surrogate.experimental_correction import cfd_metadata
            s._df_metadata = cfd_metadata(s._K_arr, s._cF_arr)
        # ── Re-seed P_ref_abs from the solver's ACTUAL drag (2026-07-13) ────
        # The seed above used the uniform-geometry (K0, cF0); the zone_config /
        # zone_arrays paths then swap in per-row graded K/cF (constructor or
        # override_simple_K_cF). P_ref_abs is the PHYSICAL outlet absolute
        # pressure (ledger C8) — leaving the uniform seed on a graded design
        # anchors the outlet at the wrong pressure by (Δp_graded − Δp_uniform),
        # which feeds ρ = P_abs/(RT) everywhere: the C8 mechanism surviving on
        # the zoned branch. Per-row C averaged arithmetically (rows are drag in
        # SERIES along the stream). Guarded on genuine non-uniformity so the
        # uniform path never recomputes — bit-identical there (same reasoning
        # as the kernels' use_eps guard).
        if fluid_type == 'ideal_gas':
            _K_rows = np.asarray(s._K_arr, dtype=np.float64)
            _cF_rows = np.asarray(s._cF_arr, dtype=np.float64)
            if (float(_K_rows.max()) != float(_K_rows.min())
                    or float(_cF_rows.max()) != float(_cF_rows.min())):
                _C_rows = (_mu_in * _G / np.maximum(_K_rows, 1e-16)
                           + _cF_rows * _G * _G)
                _P_out_sq_g = predict_outlet_p_sq(
                    float(P_in_abs), float(T_in_f),
                    float(np.mean(_C_rows)), L_stream)
                s.P_ref_abs = float(np.sqrt(max(_P_out_sq_g, 1.0e4)))
        # ── C8 shooting: reseed from the PREVIOUS iteration's MEASURED drag
        # (openspec c8-p-in-shooting). The 1D seed above (and its graded
        # refinement) only ESTIMATE the drag, so the realized inlet absolute
        # pressure P_ref_abs + Δp_solved misses the specified P_in (ledger
        # C8: case 16 realized 288980 vs spec 304746, −5.2%). The P² update
        #     P_out²_new = P_in² − (realized_prev² − P_ref_prev²)
        # reuses the 1D compressible invariant (P_in²−P_out² = 2RT̄CL, level-
        # free) with the solver-measured drag integral, landing the realized
        # inlet on spec in 1–2 outer iterations. Overrides BOTH seeds above
        # (measured drag supersedes any estimate). Same clip posture as the
        # seeds: 1e4 Pa floor, no raise (2D has no choke guard — ledger O1,
        # deliberately a separate change).
        if (fluid_type == 'ideal_gas' and p_shoot_prev is not None
                and cfg.get('p_in_shooting',
                            os.environ.get('TPMSHX_P_IN_SHOOT', '0') == '1')):
            _pref_prev, _dp_prev = float(p_shoot_prev[0]), float(p_shoot_prev[1])
            _P_out_sq_shoot = (float(P_in_abs) ** 2
                               - _dp_prev * (_dp_prev + 2.0 * _pref_prev))
            s.P_ref_abs = float(np.sqrt(max(_P_out_sq_shoot, 1.0e4)))
        _has_partial = np.any(s.outlet_frac < 0.99) and np.any(s.outlet_frac > 0.5)
        # R3 (2026-07-07): production solver knobs, precedence
        # env > SolverConfig > dim-specific auto. The autos are the
        # long-standing hardcodes (partial 5e-4 / full 1e-5, cap 10000);
        # a None config keeps them bit-identically. TPMSHX_SIMPLE_TOL
        # used to be honoured by 3D only — the asymmetry is gone.
        _tol = 5e-4 if _has_partial else 1e-5
        _max_it = 10000
        _sol_knobs = getattr(cfg.get('compute_cfg'), 'solver', None)
        if _sol_knobs is not None:
            if _sol_knobs.tol_simple is not None:
                _tol = float(_sol_knobs.tol_simple)
            if _sol_knobs.max_iter_simple is not None:
                _max_it = int(_sol_knobs.max_iter_simple)
        _env_tol = os.environ.get('TPMSHX_SIMPLE_TOL')
        if _env_tol is not None:
            _tol = float(_env_tol)
        # Propagate Ta/Tb to SIMPLE.T_field if available (compressible coupling
        # fix; without this _update_density uses stale scalar T_in inside SIMPLE)
        if T_field_real is not None:
            T_simple = _to_simple_coords(T_field_real)
            if T_simple.shape == s.T_field.shape:
                s.update_T_field(np.ascontiguousarray(T_simple))
        # Live residual hook — push (iter, residual) onto the shared
        # buffer (captured from the enclosing _build_fields_cfg
        # ``live_residuals`` parameter) so the UI sparkline can render
        # during the solve instead of only after it returns. ``None``
        # disables the hook for headless pipeline runs.
        _buf = live_residuals
        _side = 'A' if 'A' in label else 'B'
        def _progress_cb(it, res, _s=_side):
            if _buf is None:
                return
            _buf.setdefault(_s, []).append((int(it), float(res)))
        # 2026-05-07: 2D SIMPLE max_iter 5000 → 10000. Crossflow with
        # partial-B inlet (e.g. user's pipeB w=0.068m of L=0.182) +
        # high-u Forchheimer-branch needs more iters to drive residual
        # below tol. 5000 left B at res~3e-3 with target 1e-3.
        # ── Ledger C9 / F2 convergence gates ────────────────────────────
        # DEFAULT ON in the pipeline, mirroring 3D (ledger C7). The legacy `tol`
        # gates `_mass_res_jit`, a PLANE-INTEGRATED flux defect that the pp solve
        # makes TAUTOLOGICALLY ZERO on a full-face outlet (measured 1.6e-15), so
        # it fires at the min-iter floor (iteration 20) and stops the solve there
        # — under-converging dP_A by 3.3 %. F2 gates on the momentum residual +
        # solved-cell continuity + global boundary mass instead.
        #
        # NOT `tol_simple`: that name already means several different numbers
        # across the codebase and it still drives the legacy path. F2 gets its own
        # names so nothing forks silently (codex review P0-4).
        # precedence: env > SolverConfig > cfg > default (same shape as `_tol`)
        def _f2_knob(name, default):
            v = getattr(_sol_knobs, name, None) if _sol_knobs is not None else None
            if v is None:
                v = cfg.get(name)
            return default if v is None else v

        s.convergence_mode = str(os.environ.get(
            'TPMSHX_CONV_MODE', _f2_knob('convergence_mode', 'f2')))
        s.mom_tol = float(_f2_knob('mom_tol', 1e-4))
        s.mass_local_tol = float(_f2_knob('mass_local_tol', 1e-6))
        s.mass_global_tol = float(_f2_knob('mass_global_tol', 1e-6))

        conv, n_it = s.solve(max_iter=_max_it, tol=_tol, verbose=False,
                               progress_cb=_progress_cb, cancel_check=cancel_check)
        if not conv:
            # Under f2 the legacy `residuals[-1]` is the C9 tautology (~1e-15
            # on a full-face outlet) — quoting it makes a FAILED solve look
            # converged. Report the gates that actually held the exit open.
            if str(getattr(s, 'convergence_mode', 'legacy')) == 'f2':
                simple_warnings[label] = (
                    f"SIMPLE ({label}): not converged after {n_it} iters "
                    f"(exit={getattr(s, 'exit_reason', '?')}, "
                    f"mom={getattr(s, 'final_res_mom', None)}, "
                    f"mass_local={getattr(s, 'final_res_mass_local', None)}, "
                    f"mass_global={getattr(s, 'final_res_mass_global', None)})")
            else:
                simple_warnings[label] = (
                    f"SIMPLE ({label}): not converged after {n_it} iters "
                    f"(res={s.residuals[-1]:.2e})")
        else:
            # A converged re-solve SUPERSEDES an earlier failure on the same
            # side (2026-07-12). This dict is keyed by label and was only ever
            # WRITTEN on failure, never cleared — so one stalled warm-up solve
            # stuck for the whole run and forced solver_converged=False even
            # though every field the run reported came from a converged solve.
            # The outer loop re-solves SIMPLE on every iteration, so the early
            # ones are transient warm-starts, not the answer. Mirrors the 3D
            # fix (judge the FINAL solve per side).
            simple_warnings.pop(label, None)

        # Extract cell-centre velocities (wall-masked for energy solver)
        u_m, v_m = s.get_wall_masked_velocity()
        main_cc = 0.5 * (v_m[:, :-1] + v_m[:, 1:])    # main flow (v in SIMPLE)
        cross_cc = 0.5 * (u_m[:-1, :] + u_m[1:, :])   # cross flow (u in SIMPLE)
        if is_x:
            # SIMPLE (perp=Ny, flow=Nx) → real (Nx, Ny)
            uc_real = main_cc.T     # main flow → x
            vc_real = cross_cc.T    # cross flow → y
            if d == 1:  # -x: flip
                uc_real = -uc_real[::-1, :]
                vc_real = vc_real[::-1, :]
        else:
            vc_real = main_cc       # main flow → y
            uc_real = cross_cc      # cross flow → x
            if d == 3:  # -y: flip
                vc_real = -vc_real[:, ::-1]
                uc_real = uc_real[:, ::-1]

        return uc_real, vc_real, s

    fields = {
        'energy_dx': energy_dx, 'energy_dy': energy_dy,
        '_x_breaks': _x_breaks, '_y_breaks': _y_breaks,
        '_run_simple': _run_simple,
        'simple_warnings': simple_warnings,
    }
    return fields


def _run_solvers_cfg(cfg: dict[str, Any], fields: dict[str, Any], *,
                     progress_cb: Callable[[int], None] | None = None,
                     cancel_token: Any = None,
                     ui_hooks: dict | None = None) -> dict[str, Any]:
    """Phase 3 (Qt-free): drive ``_run_solvers`` via the
    :class:`_PipelineWindowShim` adapter.

    Audit C4 (L-a-2). ``progress_cb`` is fired indirectly: the shim's
    ``__setattr__`` forwards any ``_compute_progress`` write inside
    the solver loop to ``progress_cb`` as an integer 0–100. The
    enclosing :class:`ComputePipeline.run` adds its own 20 / 90 / 100
    ticks around the three phases.

    ``cancel_token`` is polled at solver iteration/chunk boundaries.

    ``ui_hooks`` (B2 2.1a): optional dict; ``'iter_label_cb'`` receives
    the shim-captured ``_iter_label_now`` strings ("iter k/N").
    """
    compute_cfg = cfg['compute_cfg']
    _hooks = ui_hooks or {}
    shim = _PipelineWindowShim(compute_cfg, progress_cb=progress_cb,
                               iter_label_cb=_hooks.get('iter_label_cb'))
    cancel_check = (None if cancel_token is None else
                    lambda: bool(getattr(cancel_token, 'cancelled', False)))
    result = _run_solvers(shim, cfg, fields, cancel_check=cancel_check)
    # Forward shim-captured state into the result dict so Pipeline2D's
    # finalize step can promote it into ComputeResult slots.
    result['_shim_zone_axis_dir'] = shim._zone_axis_dir
    result['_shim_zone_stats'] = shim._zone_stats
    result['_shim_zone_boundaries'] = shim._zone_boundaries
    result['_shim_zone_boundaries_x'] = shim._zone_boundaries_x
    result['_shim_zone_boundaries_y'] = shim._zone_boundaries_y
    # Fluid + solid properties — needed by ComputeResult.props.
    result['_shim_rho_A'] = shim._rho_A
    result['_shim_rho_B'] = shim._rho_B
    result['_shim_mu_A'] = shim._mu_A
    result['_shim_mu_B'] = shim._mu_B
    result['_shim_K_ffA'] = shim._K_ffA
    result['_shim_K_ffB'] = shim._K_ffB
    result['_shim_K_ss'] = shim._K_ss
    result['_shim_h_vA'] = shim._h_vA
    result['_shim_h_vB'] = shim._h_vB
    return result


def _finalize_cfg(raw: dict[str, Any],
                  fields: dict[str, Any]) -> ComputeResult:
    """Phase 4 (Qt-free): assemble a :class:`ComputeResult` from the
    raw ``_run_solvers_cfg`` output and the original ``fields`` dict.

    Audit C4 (L-a-2): no window writes; everything moves through the
    returned :class:`domain.compute_result.ComputeResult`.
    Legacy ``_store_results(window, cfg, result)`` becomes a thin
    adapter that copies the result's slots into the UI attributes
    that ``finalize_plots`` already reads from ``window``.

    The ``fields`` dict still holds the parsed-input cfg dict under
    key ``compute_cfg`` (the original :class:`ComputeConfig`) plus
    ``N_x`` / ``N_y`` / ``L`` / ``H`` / ``dir_A`` / ``dir_B`` /
    ``zone_config`` / ``za`` — the same keys ``_store_results`` read
    from the parsed-cfg dict.
    """
    Ta, Tb, Ts = raw['Ta'], raw['Tb'], raw['Ts']
    ucA, vcA = raw['ucA'], raw['vcA']
    ucB, vcB = raw['ucB'], raw['vcB']

    # Mass-weighted outlet T per side using the same enthalpy balance
    # _run_solvers used for Q_A_fine / Q_B_fine; that gives the same
    # T_out a downstream finalize_plots would compute by hand.
    compute_cfg = fields['compute_cfg']

    def _outlet_T(T_field, uc_field, vc_field, dir_code, fluid_type,
                  T_in_K, P_in_Pa):
        # B1 1.1: param renamed from `fluid_props` — it shadowed the
        # solvers.fluid_props module this function now dispatches through.
        from sjtu_tpmshx.solvers import fluid_props as _fluids
        # Same convention as ``_enthalpy_balance_2d`` outlet plane.
        import numpy as _np
        # Zoned-ε outlet weighting (2026-07-13 audit): the physical mass flux
        # through an outlet cell is ε·ρ·|u|·dA. A missing ε cancels when ε is
        # uniform along the outlet plane (every run without zoned ε — weights
        # unchanged, bit-identical) but mis-weights T_out on zoned designs,
        # inconsistent with the N1-fixed Q weighting. The FULL ε is enough:
        # the per-side asym split ratio s is a scalar and cancels in the
        # weighted average.
        _za_f = fields.get('za')
        _eps2d = None
        if _za_f is not None and _za_f.get('eps_arr') is not None:
            _e = _np.asarray(_za_f['eps_arr'], dtype=_np.float64)
            if _e.shape == _np.asarray(T_field).shape:
                _eps2d = _e
        if dir_code in (0, 1):
            j_out = -1 if dir_code == 0 else 0
            u_face = uc_field[j_out, :]
            T_face = T_field[j_out, :]
            eps_face = _eps2d[j_out, :] if _eps2d is not None else 1.0
            dA = raw['energy_dy']
        else:
            i_out = -1 if dir_code == 2 else 0
            u_face = vc_field[:, i_out]
            T_face = T_field[:, i_out]
            eps_face = _eps2d[:, i_out] if _eps2d is not None else 1.0
            dA = raw['energy_dx']
        # ε·ρ·cp weighting — registry primitives (water rho ignores P).
        _m = _fluids.get(fluid_type)
        rho = _m.rho(T_face, P_in_Pa)
        cp = _m.cp(T_face, P_in_Pa)
        w = eps_face * _np.asarray(rho) * _np.asarray(cp) * _np.abs(u_face) * dA
        wsum = float(_np.sum(w))
        if wsum < 1e-30:
            return float(_np.mean(T_face))
        return float(_np.sum(w * T_face) / wsum)

    T_out_A = _outlet_T(Ta, ucA, vcA, fields['dir_A'],
                        compute_cfg.fluid_A.type,
                        compute_cfg.fluid_A.T_in_K,
                        compute_cfg.fluid_A.P_in_Pa)
    T_out_B = _outlet_T(Tb, ucB, vcB, fields['dir_B'],
                        compute_cfg.fluid_B.type,
                        compute_cfg.fluid_B.T_in_K,
                        compute_cfg.fluid_B.P_in_Pa)

    # Zone slot — None when zones disabled.
    zones_slot = None
    if (raw.get('_shim_zone_axis_dir') is not None
            or raw.get('_shim_zone_stats') is not None):
        zones_slot = {
            'axis_dir': raw.get('_shim_zone_axis_dir'),
            'stats': raw.get('_shim_zone_stats'),
            'boundaries': raw.get('_shim_zone_boundaries'),
            'boundaries_x': raw.get('_shim_zone_boundaries_x'),
            'boundaries_y': raw.get('_shim_zone_boundaries_y'),
        }

    # TPMS geometry derived from cfg (eps + D_h + A_0) for props slot.
    eps_geom, D_h_m, A_0_m2 = geometry_props(compute_cfg)

    return ComputeResult(
        Q_W=safe_float(raw['Q_total']),
        dP_A_Pa=safe_float(raw['dP_A']),
        dP_B_Pa=safe_float(raw['dP_B']),
        # Fail-safe default: a missing/renamed key must read as NOT converged,
        # not silently report success (blind-spot audit W5, 2026-07-07).
        converged=bool(raw.get('solver_converged', False)),
        T_out_A_K=T_out_A,
        T_out_B_K=T_out_B,
        fields={
            'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
            'ucA': ucA, 'vcA': vcA, 'ucB': ucB, 'vcB': vcB,
            # N5: display-smoothed copies (None on full-face runs ⇒ use raw)
            'ucA_disp': raw.get('ucA_disp'), 'vcA_disp': raw.get('vcA_disp'),
            'ucB_disp': raw.get('ucB_disp'), 'vcB_disp': raw.get('vcB_disp'),
            'P_fA': raw['P_fA'], 'P_fB': raw['P_fB'],
            'dx_arr': raw['energy_dx'], 'dy_arr': raw['energy_dy'],
            'N_x': fields['N_x'], 'N_y': fields['N_y'],
            'L': fields['L'], 'H': fields['H'],
            'dir_A': fields['dir_A'], 'dir_B': fields['dir_B'],
            'zone_config': fields['zone_config'],
            'za': fields['za'],
        },
        coeffs={
            'K_ffA': raw.get('_shim_K_ffA'),
            'K_ffB': raw.get('_shim_K_ffB'),
            'K_ss': raw.get('_shim_K_ss'),
            'h_vA': raw.get('_shim_h_vA'),
            'h_vB': raw.get('_shim_h_vB'),
        },
        props={
            'rho_A': raw.get('_shim_rho_A'),
            'rho_B': raw.get('_shim_rho_B'),
            'mu_A': raw.get('_shim_mu_A'),
            'mu_B': raw.get('_shim_mu_B'),
            'eps_A': eps_geom,
            'D_h_m': D_h_m,
            'A_0_m2': A_0_m2,
        },
        residuals={
            'r_dP_A': float('nan'),  # _run_solvers does not surface
            'r_dP_B': float('nan'),
            'r_Q': 1.0 if raw.get('Q_richardson_warn') else 0.0,
            'simple_A': raw.get('residuals_A'),
            'simple_B': raw.get('residuals_B'),
            'mass_imbalance_rel_A': float(
                raw.get('mass_imbalance_rel_A', float('nan'))),
            'mass_imbalance_rel_B': float(
                raw.get('mass_imbalance_rel_B', float('nan'))),
            'Q_A': float(raw.get('Q_A', float('nan'))),
            'Q_B': float(raw.get('Q_B', float('nan'))),
            'Q_net': float(raw.get('Q_net', float('nan'))),
            'energy_imbalance_rel': float(
                raw.get('energy_imbalance_rel', float('nan'))),
            'enthalpy_imbalance_rel': float(
                raw.get('energy_imbalance_rel', float('nan'))),
        },
        zones=zones_slot,
        warnings=list(raw.get('warnings_list', [])),
        extrap_reasons=list(fields.get('extrap_reasons', [])),
        diagnostics={
            # Dimension marker for write_result dispatch (C4).
            'mode': '2d',
            'Q_enthalpy_A': raw.get('Q_enthalpy_A'),
            'Q_enthalpy_B': raw.get('Q_enthalpy_B'),
            'Q_solid_richardson': raw.get('Q_solid_richardson'),
            'Q_richardson_warn': bool(raw.get('Q_richardson_warn', False)),
            'mass_flow_A_kg_s_per_m': float(
                raw.get('mass_flow_A_kg_s_per_m', float('nan'))),
            'mass_flow_B_kg_s_per_m': float(
                raw.get('mass_flow_B_kg_s_per_m', float('nan'))),
            # 2026-07-12: solve_2d produced all three of these on the raw dict
            # and none of them were forwarded — every ComputeResult consumer
            # was blind to the 2D compressible-envelope verdict and to the
            # P_abs-clip engagement (the 3D side had the same gap for
            # p_clip_hits; both are closed now).
            'envelope_valid': raw.get('envelope_valid', True),
            'envelope_reasons': list(raw.get('envelope_reasons', [])),
            'p_clip_hits': int(raw.get('p_clip_hits', 0)),
            # C8 shooting diagnostics (openspec c8-p-in-shooting): realized
            # inlet absolute pressure vs the specified P_in, per ideal-gas
            # side (NaN otherwise). Forwarded here for the same reason as
            # envelope_valid above — a raw-dict-only key is invisible to
            # every ComputeResult consumer.
            'P_in_realized_A': float(raw.get('P_in_realized_A', float('nan'))),
            'P_in_shoot_resid_A': float(
                raw.get('P_in_shoot_resid_A', float('nan'))),
            'P_in_realized_B': float(raw.get('P_in_realized_B', float('nan'))),
            'P_in_shoot_resid_B': float(
                raw.get('P_in_shoot_resid_B', float('nan'))),
            # Per-gate breakdown behind ComputeResult.converged, so a caller
            # can see WHICH gate failed (convergence truth-table).
            'convergence_detail': raw.get('convergence_detail'),
        },
        metadata={'darcy_forchheimer': raw.get('df_metadata')},
    )


# B2 2.1b: the _store_results(window, cfg, result) adapter was DELETED —
# Main_Menu.write_result (ui/mixins/run_controller.py) is the single
# ComputeResult→window copy now. Note: the old dict's residuals_A/B
# snapshots are not forwarded (they only fed the removed 2D convergence
# plot; verified no UI consumer).
