"""pipelines/stages_3d.py — 3D compute stage functions for SJTU-TPMSHX.

Mirrors `pipelines.stages_2d` (2D) but dispatches the 3D stack:
    SIMPLESolver3D (fluid A: air compressible, fluid B: air or water) +
    LTNE 3-temp coupling + solve_full_domain_3d (3D LTNE) + outer non-iso.

MVP (2026-04-20): uniform geometry only (no zoning from UI). Mirrors
`validation/cases/validate_shanghai_3d_real.py::_run_one_case` but with UI-sourced
parameters instead of Shanghai Excel.

Entry: the cfg stage functions consumed by
controllers.compute_pipeline.Pipeline3D (_parse_inputs_3d_cfg →
_build_fields_3d_cfg → _run_solvers_3d_cfg → _finalize_3d_cfg).
    (visualisation — finalize_plots_3d(window) — lives in
     ui/plot_3d_results.py so this module stays Qt/matplotlib-free.)

Moved out of `runs/run_calculation_3d.py` in batch-3 (2026-06-13) to fix
the controllers→runs layer inversion.  This module imports nothing from
`runs/` or `controllers/` (contracts-layer split 2026-07-02: ComputeConfig /
ComputeResult now come from `domain`, killing the old pipelines↔controllers
cycle and its deferred imports).

The finished :class:`ComputeResult` carries the 3D render/export contract
(``fields`` arrays, headline scalars, ``diagnostics['mode']='3d'``);
``Main_Menu.write_result`` publishes it to ``window._result_3d``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from domain.compute_config import ComputeConfig, bc_to_dict
from domain.compute_result import ComputeResult
from solvers.tpms_calc import geometry as tpms_geometry
from solvers.asym_split import (
    _asym_split_A, _per_side_eps_override, _eps_sides_for_run,
)

from pipelines._stage_common import (
    validate_domain_dims, surrogate_extrap_reasons, safe_float as _safe_float,
    geometry_props,
)
from pipelines.stages_3d_helpers import (  # Phase 3: extracted pure helpers
    _stream_axis, _dir_is_reverse, _inlet_index, _outlet_index,
    _face_slice, _real_outlet_slice, _dilate_one_step_3d, _box_smooth_3d,
    _build_partial_masks, _solver_velocity_to_real, _solver_staggered_to_real,
    _balance_stream_outflow, _build_chi_B_union_extrude,
    _build_chi_B_mass_flux_threshold, _build_chi_B_velocity_threshold,
)

# ── Re-exports (openspec split-pipelines, 2026-07-03) ────────────────────────
# External consumers (tests, runs/, validation/, projects/) import these
# names from pipelines.stages_3d; keep every moved name reachable here.
# The implementations moved VERBATIM to pipelines.flux_3d / pipelines.grid_3d
# / pipelines.run_stack_3d — behavior bit-identical.
from pipelines.flux_3d import (  # noqa: F401
    _UI_ROUGH_MODE_DEFAULT, _resolve_ui_roughness, _face_flux_weights,
    _mass_weighted_T_out, _mass_weighted_h_out, _sco2_hv_local_field,
    _simple_mass_flow, _apply_roughness_KcF, _apply_roughness_h_v,
)
from pipelines.grid_3d import (  # noqa: F401
    _resolve_axis_map, _build_zone_fields_3d, _build_grid_3d,
    _solver_spacings,
)
from pipelines.run_stack_3d import (  # noqa: F401
    R_AIR, _MAX_OUTER, _OUTER_TOL, _ALPHA_T,
    _M4_DEFAULT_EXPONENT, _M4_DEFAULT_MODE,
    _seed_p_ref, _simple_tol_default, _apply_phase_flags, _apply_accel_flags,
    _prof_3d_enabled, _prof_res_trace, _run_two_simple_parallel,
    _conservation_diagnostics_3d, _run_3d_stack,
)


# B2 2.1c (2026-06-13): the legacy window entrypoints
# run_calculation_3d_inner / run_calculation_3d_inner_cfg and the
# _parse_inputs window adapter were DELETED — the GUI 3D path drives
# controllers.compute_pipeline.Pipeline3D (cfg stage functions below);
# B3 (2026-06-13) retired the transitional raw_3d carrier: the GUI 3D path
# now publishes the ComputeResult directly as window._result_3d
# (Main_Menu.write_result), so diagnostics['raw_3d'] no longer exists.


# ── 3D result visualisation (PyVistaQt panel + 2D mid-z slice canvases) was
#    extracted to ui/plot_3d_results.py (2026-06-09 Group-4 slice A1/A2):
#    finalize_plots_3d / _render_2d_slices_from_3d / _plot_3d_{temperature,
#    pressure,velocity} / _begin_canvas_plot / _style_axis /
#    _store_3d_result_labels / _fmt_metric. Moved out so this compute module
#    no longer imports ui.theme / matplotlib (C4 'Qt-free' contract).


# ─────────────────────────── internals ────────────────────────────

def _parse_inputs_3d_cfg(compute_cfg: ComputeConfig) -> dict[str, Any]:
    """Phase 1 (Qt-free) 3D mirror of ``_parse_inputs(window, compute_cfg)``.

    Audit C4 (L-a-2): reads only :class:`ComputeConfig`. Returns the
    same parsed dict ``_run_3d_stack`` expects plus an
    ``extrap_reasons`` key (the legacy version mutated this onto
    ``window._extrap_reasons``).
    """
    # ── scalar geometry + grid + fluids ─────────────────────────────
    L = compute_cfg.geometry.L_dom_m
    H = compute_cfg.geometry.H_dom_m
    Lz = (compute_cfg.geometry.Lz_m
          if compute_cfg.geometry.Lz_m is not None else 0.042)
    Nx = compute_cfg.solver.Nx
    Ny = compute_cfg.solver.Ny
    Nz = compute_cfg.solver.Nz

    for name, val in [('L', L), ('H', H), ('Lz', Lz)]:
        if val <= 0:
            raise ValueError(
                f"Domain dimension {name!r} must be > 0 (got {val})")
    validate_domain_dims([('L', L), ('H', H), ('Lz', Lz)])
    for name, val in [('Nx', Nx), ('Ny', Ny), ('Nz', Nz)]:
        if val < 1:
            raise ValueError(
                f"Grid count {name!r} must be >= 1 (got {val})")

    u_A = compute_cfg.fluid_A.u_mps
    u_B = compute_cfg.fluid_B.u_mps
    T_inA = compute_cfg.fluid_A.T_in_K
    T_inB = compute_cfg.fluid_B.T_in_K
    T_s_init = compute_cfg.solver.T_s_init_K
    P_inA = compute_cfg.fluid_A.P_in_Pa
    P_inB = compute_cfg.fluid_B.P_in_Pa
    Lcell = compute_cfg.geometry.L_cell_mm
    t_wall = compute_cfg.geometry.t_wall_mm
    k_s = compute_cfg.geometry.k_s_W_mK
    tpms_type = compute_cfg.geometry.tpms

    g = tpms_geometry(tpms_type, Lcell, t_wall, k_s)
    eps = g['epsilon']
    D_h = g['D_h']

    # Partial-pipe BC dicts — side A full-face fallback, side B raw partial.
    fluid_A_cfg = bc_to_dict(compute_cfg.bc_A, L, H, side='A', with_z=True)
    fluid_B_cfg = bc_to_dict(compute_cfg.bc_B, L, H, side='B', with_z=True)
    if fluid_B_cfg is None:
        # A degenerate B BC (the PartialBCConfig default in_w=out_w=0) reaching
        # THIS ComputeConfig→3D boundary means "full-face cross-flow B", NOT a
        # single-fluid run: via ComputeConfig fluid_B is always a configured 2nd
        # fluid (validated below). bc_to_dict(side='B') returns None for that
        # degenerate case and DROPS the direction; _run_3d_stack's
        # `if fB is not None` gate then skips the entire B SIMPLE build (the
        # A-alone path), so the 2-fluid solve silently returns nan (air uncooled,
        # T_out_B=nan, E_imbal=1.0). Rebuild a full-face dict via the side='A'
        # fallback, which preserves bc_B.dir. The genuine single-fluid A-alone
        # path reaches _run_3d_stack with an explicit fluid_B_cfg=None and
        # bypasses this boundary (e.g. audit_3d_conservation T5), so it — and
        # bc_to_dict's documented side-B None asymmetry — are unaffected.
        fluid_B_cfg = bc_to_dict(compute_cfg.bc_B, L, H, side='A', with_z=True)

    # Surrogate-domain extrap guard — cfg.extrap.allow drives it
    # (shared both-side check in _stage_common; ImportError → skip,
    # ValueError propagates).
    extrap_reasons = surrogate_extrap_reasons(
        compute_cfg, bool(compute_cfg.extrap.allow))

    from solvers.tpms_calc import validate_fluid_type
    fluid_type_A = compute_cfg.fluid_A.type
    fluid_type_B = compute_cfg.fluid_B.type
    validate_fluid_type(fluid_type_A, 'A')
    validate_fluid_type(fluid_type_B, 'B')

    # Feature flags — sourced from cfg.flags + cfg.zones.
    wall_refine = bool(compute_cfg.flags.wall_refine_3d)
    zone_grid_cells = None
    if (compute_cfg.zones.enabled and compute_cfg.zones.grid is not None):
        zg = compute_cfg.zones.grid
        if isinstance(zg, dict) and zg.get('cells'):
            zone_grid_cells = zg['cells']

    return dict(
        L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
        u_A=u_A, u_B=u_B, T_inA=T_inA, T_inB=T_inB,
        P_inA=P_inA, P_inB=P_inB,
        T_s_init=T_s_init,
        envelope_mode=getattr(compute_cfg, 'envelope_mode', 'raise'),
        Lcell=Lcell, t_wall=t_wall, k_s=k_s, tpms_type=tpms_type,
        eps=eps, D_h=D_h,
        delta_levelset=float(compute_cfg.geometry.delta_levelset),
        fluid_A_cfg=fluid_A_cfg,
        fluid_B_cfg=fluid_B_cfg,
        wall_refine_3d=wall_refine,
        variable_rho_cp=bool(compute_cfg.flags.variable_rho_cp),
        # R3 (2026-07-07): production solver knobs (None = run_stack's
        # dim-specific autos; see SolverConfig docstring).
        tol_simple=compute_cfg.solver.tol_simple,
        max_iter_simple=compute_cfg.solver.max_iter_simple,
        max_outer_ltne=compute_cfg.solver.max_outer_ltne,
        outer_tol_K=compute_cfg.solver.outer_tol_K,
        zone_grid_cells=zone_grid_cells,
        fluid_type_A=fluid_type_A,
        fluid_type_B=fluid_type_B,
        extrap_reasons=extrap_reasons,
        compute_cfg=compute_cfg,
    )


def _build_fields_3d_cfg(parsed: dict[str, Any]) -> dict[str, Any]:
    """Phase 2 (Qt-free) 3D: passthrough.

    Audit C4 (L-a-2). The 3D stack has no separate build phase — the
    cfg dict from :func:`_parse_inputs_3d_cfg` is consumed directly by
    :func:`_run_3d_stack`. This stub keeps the Pipeline ABC contract
    symmetric with 2D: ``build_fields → run_solvers → finalize``.
    """
    return parsed


def _run_solvers_3d_cfg(parsed: dict[str, Any], fields: dict[str, Any], *,
                         progress_cb: Callable[[int], None] | None = None,
                         cancel_token: Any = None,
                         iter_cb: Callable[[int, int], None] | None = None,
                         ) -> dict[str, Any]:
    """Phase 3 (Qt-free) 3D: drive :func:`_run_3d_stack` with the
    progress + cancel hooks read off the cfg dict.

    Audit C4 (L-a-2). Wraps the existing ``_run_3d_stack(cfg)`` body
    without modifying it.  ``parsed`` and ``fields`` are the same dict
    (the build phase is a passthrough); the Pipeline ABC contract
    surfaces both so the signature matches :class:`Pipeline2D`.

    ``iter_cb(outer, n_outer)`` (B2 2.1a) mirrors the legacy window
    path's ``cfg['_iter_cb']`` wiring — drives the UI "outer k/N"
    ticker label through the SIMPLE↔LTNE coupling loop.
    """
    cfg = dict(parsed)  # shallow copy — _run_3d_stack mutates a few keys

    # Progress + cancel hooks (mirrors legacy run_calculation_3d_inner_cfg).
    if progress_cb is not None:
        cfg['_progress_cb'] = (lambda pct, _cb=progress_cb: _cb(int(pct)))
    if cancel_token is not None:
        cfg['_cancel_check'] = (lambda _tok=cancel_token:
                                bool(getattr(_tok, 'cancelled', False)))
    if iter_cb is not None:
        cfg['_iter_cb'] = iter_cb

    # Phase A/B/C acceleration flags — see _apply_phase_flags.
    _apply_phase_flags(cfg)

    return _run_3d_stack(cfg)


def _finalize_3d_cfg(raw: dict[str, Any],
                     fields: dict[str, Any]) -> ComputeResult:
    """Phase 4 (Qt-free) 3D: assemble a :class:`ComputeResult` from the
    ``_run_3d_stack`` output.

    Audit C4 (L-a-2). The 3D result dict is much richer than the 2D
    one — most fields land in ``ComputeResult.fields`` /
    ``ComputeResult.diagnostics``. The headline scalars (``Q_total``,
    ``dP_A`` / ``dP_B``, ``T_out_A`` / ``T_out_B``) lift directly.

    B3 C5 (2026-06-13): the ComputeResult is now the SINGLE result carrier.
    ``Main_Menu.write_result`` publishes it directly as
    ``window._result_3d`` and ``ui/plot_3d_results`` reads ``res.fields`` /
    the dataclass attributes — the old raw-dict ``diagnostics['raw_3d']``
    carrier is gone. The render/export contract (every key the renderer +
    CSV/NPZ export consume) is locked by
    ``tests/test_finalize_3d_result_sync.py``.
    """
    compute_cfg = fields.get('compute_cfg')

    # B2 2.1c (2026-06-13): mirror the legacy extrap tagging onto the raw
    # dict (the retired window path stamped these after _run_3d_stack) so
    # the live carrier below is self-contained.
    raw['extrapolated'] = bool(fields.get('extrap_reasons'))
    raw['extrap_reasons'] = list(fields.get('extrap_reasons', []))

    # 3D solver already computed mass-weighted outlet T per side.
    # _safe_float (shared _stage_common.safe_float): None / non-numeric → nan.
    T_out_A = _safe_float(raw.get('T_out_A', raw.get('T_A_out')))
    T_out_B = _safe_float(raw.get('T_out_B', raw.get('T_B_out')))

    # TPMS geometry (eps + D_h + A_0) for props slot.
    eps_geom = D_h_m = A_0_m2 = float('nan')
    if compute_cfg is not None:
        eps_geom, D_h_m, A_0_m2 = geometry_props(compute_cfg)

    return ComputeResult(
        Q_W=_safe_float(raw.get('Q_total', raw.get('Q'))),
        dP_A_Pa=_safe_float(raw.get('dP_A', raw.get('dP'))),
        dP_B_Pa=_safe_float(raw.get('dP_B')),
        # Fail-safe default: a missing/renamed key must read as NOT converged,
        # not silently report success (blind-spot audit W5, 2026-07-07).
        converged=bool(raw.get('solver_converged', False)),
        T_out_A_K=T_out_A,
        T_out_B_K=T_out_B,
        fields={
            'Ta': raw.get('Ta'),
            'Tb': raw.get('Tb'),
            'Ts': raw.get('Ts'),
            'P_fA': raw.get('P_Pa'),
            'P_fB': raw.get('P_Pa_B'),
            'ucA': raw.get('uc_real'),
            'vcA': raw.get('vc_real'),
            'wcA': raw.get('wc_real'),
            'ucB': raw.get('uc_real_B'),
            'vcB': raw.get('vc_real_B'),
            'wcB': raw.get('wc_real_B'),
            'dx': raw.get('dx'),
            'dy': raw.get('dy'),
            'dz': raw.get('dz'),
            'Lx': raw.get('Lx'),
            'Ly': raw.get('Ly'),
            'Lz': raw.get('Lz'),
            # per-cell unit-cell length field (mm) — renderer label axis;
            # carried so the live UI can drop the raw_3d dict (C5).
            'L_mm': raw.get('L_mm'),
            'dir_A': raw.get('dir_A'),
            'dir_B': raw.get('dir_B'),
            'vmag_A': raw.get('vmag'),
            'vmag_B': raw.get('vmag_B'),
            'chi_B': raw.get('chi_B'),
            'h_vA_field': raw.get('h_vA_field'),
            'h_vB_field': raw.get('h_vB_field'),
        },
        coeffs={
            'K_ffA': raw.get('_audit_K_ffA'),
            'K_ffB': raw.get('_audit_K_ffB'),
            'K_ss': raw.get('_audit_K_ss'),
        },
        props={
            'eps_A': eps_geom,
            'D_h_m': D_h_m,
            'A_0_m2': A_0_m2,
            'rho_cp_A': raw.get('_audit_rho_cp_fA'),
            'rho_cp_B': raw.get('_audit_rho_cp_fB'),
            # CSV-export scalars (main._export_results) — carried so the
            # export can read ComputeResult instead of the raw_3d dict (C5).
            'u_A_in_mps': raw.get('u_A'),
            'T_in_A_K': raw.get('T_in'),
        },
        residuals={
            'Q_enthalpy_A': _safe_float(raw.get('Q_enthalpy_A')),
            'Q_enthalpy_B': _safe_float(raw.get('Q_enthalpy_B')),
            'Q_solid_B': _safe_float(raw.get('Q_solid_B')),
            'Q_sA': _safe_float(raw.get('Q_sA')),
            'Q_sB': _safe_float(raw.get('Q_sB')),
            'Q_net': _safe_float(raw.get('Q_net')),
            'Q_interior': _safe_float(raw.get('Q_interior')),
            'energy_imbalance_rel': _safe_float(
                raw.get('energy_imbalance_rel')),
            'mass_imbalance_rel_A': _safe_float(
                raw.get('mass_imbalance_rel_A')),
            'mass_imbalance_rel_B': _safe_float(
                raw.get('mass_imbalance_rel_B')),
        },
        zones=None,  # 3D zones land in fields['chi_B'] / fields['*'] directly
        # U2 (audit 2026-06-28): _run_3d_stack collects the envelope/choke
        # messages AND the explicit SIMPLE non-convergence warning on the raw
        # dict; forward them so the UI sees them (was hard-coded [], silently
        # dropping a 3D under-resolved/off-envelope flag the 2D path surfaces).
        warnings=list(raw.get('envelope_warnings', [])),
        extrap_reasons=list(fields.get('extrap_reasons', [])),
        diagnostics={
            '_ltne_info': raw.get('_ltne_info'),
            '_max_outer': raw.get('_max_outer'),
            # Dimension marker for write_result dispatch (C4); '3d' here,
            # '2d' in stages_2d._finalize_cfg.
            'mode': '3d',
            # Compressible-envelope post-solve verdict (U2): carried so the UI
            # can flag a result the warn-mode gate marked non-physical.
            'envelope_valid': raw.get('envelope_valid', True),
            'envelope_reasons': list(raw.get('envelope_reasons', [])),
            # Companion to envelope_valid: the SIMPLE P_abs-clip engagement
            # count (_run_3d_stack sums A+B side `_p_clip_hits`). It was
            # produced on the raw dict but never forwarded, so every
            # ComputeResult consumer had to hard-code a placeholder — see
            # validate_shanghai_3d_real.py --runner pipeline, which reported a
            # constant 0/valid and thereby disabled its own pressure-validity
            # filter. Informational (lifetime counter, not a validity verdict).
            'p_clip_hits': int(raw.get('p_clip_hits', 0)),
            'AB_interior': raw.get('AB_interior'),
            'Q_sA_interior': raw.get('Q_sA_interior'),
            'Q_sB_interior': raw.get('Q_sB_interior'),
        },
    )
