"""Compute pipeline ABC — unifies 2D / 3D entrypoints behind one contract.

Audit followup C4 (L-a-2, 2026-05-28).  Built on top of the
:class:`controllers.compute_config.ComputeConfig` introduced in C3
(L-a-1).

Design
------

``ComputePipeline`` is a 3-phase abstract base class:

1. :meth:`build_fields` — build aligned grid arrays, zone property
   arrays, partial-BC masks, and the SIMPLE helper closures.
2. :meth:`run_solvers`  — run the SIMPLE + LTNE outer loop.
3. :meth:`finalize`     — compute Q / dP / T_out + assemble a
   :class:`ComputeResult`.

The base :meth:`run` glues the three together, drives the
``progress_cb`` callback at 20 / 90 / 100 %, and honours cooperative
cancellation via ``cancel_token``.

Implementations
~~~~~~~~~~~~~~~

- :class:`Pipeline2D` wires the legacy
  ``runs.run_calculation._parse_inputs / _build_fields / _run_solvers /
  _store_results`` business logic. The Qt-write side (``window.T_fA = …``,
  ``window._compute_results = {…}``) is *not* in scope here; that lives
  in ``Main_Menu.write_result(result)``.

- :class:`Pipeline3D` mirrors the 3D path through
  ``solvers.simple_solver_3d`` and ``solvers.solve_full_3d``.

Both implementations are pure ``ComputeConfig`` → :class:`ComputeResult`
adapters.  No ``window.le_*`` reads, no Qt writes.

Test boundary
~~~~~~~~~~~~~

Pure-cfg construction lets tests / scripts call
``Pipeline2D(cfg).run()`` with a small JSON file and assert on the
returned :class:`ComputeResult`.  No Qt event loop needed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .compute_config import ComputeConfig


# ── Result dataclass ─────────────────────────────────────────────────


@dataclass
class ComputeResult:
    """Output of a single :class:`ComputePipeline` run.

    Headline scalars (``Q_W``, ``dP_*_Pa``, ``T_out_*_K``) match the
    numbers shown in the UI result panel.  The rich
    sub-dictionaries hold the arrays / coefficients / residuals so the
    UI adapter (``Main_Menu.write_result``) and validation scripts can
    pluck whatever they need without re-running the solver.
    """

    # ── headline scalars (UI compute panel) ──
    Q_W: float = 0.0
    dP_A_Pa: float = 0.0
    dP_B_Pa: float = 0.0
    T_out_A_K: float = 0.0
    T_out_B_K: float = 0.0

    # ── rich arrays ──
    # 2D keys: T_fA, T_fB, T_s, P_A, P_B, u_A, v_A, u_B, v_B, eps_arr,
    #          (+ axis_dir_A, axis_dir_B for plotting)
    # 3D keys: + w_A, w_B + z_centres
    fields: Dict[str, Any] = field(default_factory=dict)

    # ── porous + coupling coefficients ──
    # Keys: K_ffA, K_ffB, K_ss, h_vA, h_vB (scalar or array per zone mode)
    coeffs: Dict[str, Any] = field(default_factory=dict)

    # ── fluid + solid properties at iteration end ──
    # Keys: rho_A, rho_B, mu_A, mu_B, eps_A, D_h_m, A_0_m2
    props: Dict[str, Any] = field(default_factory=dict)

    # ── residuals ──
    # Keys: r_Q, r_dP_A, r_dP_B (relative deltas), simple_A, simple_B,
    #       ltne_outer (max-T outer iteration delta)
    residuals: Dict[str, float] = field(default_factory=dict)

    # ── zones (None when zones disabled) ──
    # Keys: axis_dir, stats, boundaries (list[float]),
    #       boundaries_x, boundaries_y (3D / grid mode)
    zones: Optional[Dict[str, Any]] = None

    # ── warnings + extrap reasons ──
    # ``warnings`` accumulates fluid-domain / zone-fallback messages.
    # ``extrap_reasons`` is the surrogate-domain audit trail consumed
    # by Main_Menu to display the watermark + status bar.
    warnings: List[str] = field(default_factory=list)
    extrap_reasons: List[str] = field(default_factory=list)

    # ── diagnostics ──
    # Keys: iter_outer, iter_simple_A, iter_simple_B, wall_time_s
    diagnostics: Dict[str, Any] = field(default_factory=dict)


# ── Pipeline ABC ─────────────────────────────────────────────────────


class CancelledError(Exception):
    """Raised by :meth:`ComputePipeline.run` when the cancel token fires."""


ProgressFn = Callable[[int], None]


class ComputePipeline(ABC):
    """3-phase abstract pipeline driven by :class:`ComputeConfig`.

    Parameters
    ----------
    cfg : ComputeConfig
        Strict-typed compute settings.  Built at the UI boundary via
        :meth:`ComputeConfig.from_qt_window` or from JSON via
        :meth:`ComputeConfig.from_json`.
    progress_cb : callable, optional
        Single-argument ``(percent: int)`` callback fired at 20 / 90 /
        100 %.  Default no-op.
    cancel_token : object, optional
        Any object with a ``cancelled`` attribute that resolves to a
        bool.  Checked before each phase; truthy value raises
        :class:`CancelledError`.

    Subclass contract
    -----------------

    ``build_fields()`` returns an *intermediate dict* that
    ``run_solvers(fields)`` consumes — the schema is implementation
    specific (2D vs 3D differ).  ``finalize(raw, fields)`` returns the
    finished :class:`ComputeResult`.
    """

    def __init__(self, cfg: ComputeConfig,
                 progress_cb: Optional[ProgressFn] = None,
                 cancel_token: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.progress_cb: ProgressFn = progress_cb or (lambda _pct: None)
        self.cancel = cancel_token

    def _check_cancel(self) -> None:
        if self.cancel is None:
            return
        if getattr(self.cancel, 'cancelled', False):
            raise CancelledError("Pipeline cancelled by user")

    def run(self) -> ComputeResult:
        """Drive the 3 phases + cancel checks + progress ticks."""
        self._check_cancel()
        fields = self.build_fields()
        self.progress_cb(20)
        self._check_cancel()
        raw = self.run_solvers(fields)
        self.progress_cb(90)
        self._check_cancel()
        result = self.finalize(raw, fields)
        self.progress_cb(100)
        return result

    # ── subclass hooks ──────────────────────────────────────────────

    @abstractmethod
    def build_fields(self) -> Dict[str, Any]:
        """Phase 1: grid arrays + zone arrays + helper closures."""

    @abstractmethod
    def run_solvers(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 2: SIMPLE + LTNE outer loop. Returns raw solver output."""

    @abstractmethod
    def finalize(self, raw: Dict[str, Any],
                 fields: Dict[str, Any]) -> ComputeResult:
        """Phase 3: assemble :class:`ComputeResult` from raw output."""


# ── 2D / 3D concrete implementations ─────────────────────────────────


class Pipeline2D(ComputePipeline):
    """2D compute pipeline backed by ``runs.run_calculation`` helpers.

    The three phases delegate to the cfg-only refactor of the legacy
    ``_parse_inputs / _build_fields / _run_solvers / _store_results``
    business logic.  Keeping the helpers in ``runs.run_calculation``
    (rather than copying them here) avoids a multi-thousand-line move
    in this PR.  A future C5 phase will hoist them.

    The legacy helpers consume *two* dicts (``parsed`` from
    ``_parse_inputs_cfg`` and ``fields`` from ``_build_fields_cfg``).
    The ABC contract surfaces only one ``fields`` dict between phases,
    so we cache ``parsed`` on the instance for ``run_solvers`` +
    ``finalize`` to reach.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parsed: Optional[Dict[str, Any]] = None

    def build_fields(self) -> Dict[str, Any]:
        from runs.run_calculation import (
            _parse_inputs_cfg, _build_fields_cfg,
        )
        self._parsed = _parse_inputs_cfg(self.cfg)
        return _build_fields_cfg(self._parsed)

    def run_solvers(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        from runs.run_calculation import _run_solvers_cfg
        assert self._parsed is not None, (
            "Pipeline2D.run_solvers called before build_fields")
        return _run_solvers_cfg(self._parsed, fields,
                                progress_cb=self.progress_cb,
                                cancel_token=self.cancel)

    def finalize(self, raw: Dict[str, Any],
                 fields: Dict[str, Any]) -> ComputeResult:
        from runs.run_calculation import _finalize_cfg
        assert self._parsed is not None, (
            "Pipeline2D.finalize called before build_fields")
        return _finalize_cfg(raw, self._parsed)


class Pipeline3D(ComputePipeline):
    """3D compute pipeline backed by ``runs.run_calculation_3d`` helpers."""

    def build_fields(self) -> Dict[str, Any]:
        from runs.run_calculation_3d import (
            _parse_inputs_3d_cfg, _build_fields_3d_cfg,
        )
        parsed = _parse_inputs_3d_cfg(self.cfg)
        return _build_fields_3d_cfg(parsed)

    def run_solvers(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        from runs.run_calculation_3d import _run_solvers_3d_cfg
        return _run_solvers_3d_cfg(fields, progress_cb=self.progress_cb,
                                    cancel_token=self.cancel)

    def finalize(self, raw: Dict[str, Any],
                 fields: Dict[str, Any]) -> ComputeResult:
        from runs.run_calculation_3d import _finalize_3d_cfg
        return _finalize_3d_cfg(raw, fields)


def pipeline_for(cfg: ComputeConfig,
                 progress_cb: Optional[ProgressFn] = None,
                 cancel_token: Optional[Any] = None) -> ComputePipeline:
    """Dim-dispatch factory: return :class:`Pipeline3D` if ``cfg.is_3d``,
    otherwise :class:`Pipeline2D`.

    Convenience wrapper for adapters / scripts that do not know upfront
    whether the cfg represents a 2D or 3D run.
    """
    if cfg.is_3d:
        return Pipeline3D(cfg, progress_cb=progress_cb,
                          cancel_token=cancel_token)
    return Pipeline2D(cfg, progress_cb=progress_cb,
                      cancel_token=cancel_token)


__all__ = [
    'ComputeResult',
    'ComputePipeline',
    'Pipeline2D',
    'Pipeline3D',
    'CancelledError',
    'pipeline_for',
]
