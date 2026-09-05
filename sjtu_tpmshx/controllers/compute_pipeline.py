"""Compute pipeline ABC — unifies 2D / 3D entrypoints behind one contract.

Audit followup C4 (L-a-2, 2026-05-28).  Built on top of the
:class:`domain.compute_config.ComputeConfig` introduced in C3
(L-a-1; contracts moved to ``domain/`` in the 2026-07-02 contracts-layer
split — ``ComputeResult`` now lives in ``domain.compute_result``).

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
  ``pipelines.stages_2d._parse_inputs / _build_fields / _run_solvers /
  _store_results`` business logic. The Qt-write side (``window.T_fA = …``,
  ``window._compute_results = {…}``) is *not* in scope here; that lives
  in ``Main_Menu.write_result(result)``.

- :class:`Pipeline3D` mirrors the 3D path through
  ``solvers.simple_solver_3d`` and ``solvers.ltne_energy_3d``.

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
from typing import Any, Callable, Dict, Optional

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.domain.run_warnings import warning_scope


# ── Pipeline ABC ─────────────────────────────────────────────────────


ProgressFn = Callable[[int], None]


class ComputePipeline(ABC):
    """3-phase abstract pipeline driven by :class:`ComputeConfig`.

    Parameters
    ----------
    cfg : ComputeConfig
        Strict-typed compute settings.  Built at the UI boundary via
        ``ui.window_config.config_from_window`` or from JSON via
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
                 cancel_token: Optional[Any] = None,
                 ui_hooks: Optional[Dict[str, Any]] = None) -> None:
        self.cfg = cfg
        self.progress_cb: ProgressFn = progress_cb or (lambda _pct: None)
        self.cancel = cancel_token
        # B2 2.1a: optional UI side channels the legacy window path wired
        # directly (live residual sparkline buffer, outer-iteration label).
        # Keys: 'live_residuals' (2D), 'iter_label_cb' (2D), 'iter_cb' (3D).
        self.ui_hooks: Dict[str, Any] = ui_hooks or {}

    def _check_cancel(self) -> None:
        if self.cancel is None:
            return
        if getattr(self.cancel, 'cancelled', False):
            raise CancelledError("Pipeline cancelled by user")

    def run(self) -> ComputeResult:
        """Drive the 3 phases + cancel checks + progress ticks."""
        # Config validation (2026-07-13, codex review): `validate()` used to
        # run ONLY on the from_dict/from_json factory paths — every direct
        # dataclass construction (gate scripts, goldens, tests, scripted
        # callers) bypassed it, so illegal F2 tolerances / grid combos went
        # straight into the solvers. The pipeline is the chokepoint every
        # run passes through; validate here, fail loud before solving.
        with warning_scope({}) as records:
            self.cfg.validate()
            self._check_cancel()
            fields = self.build_fields()
            self.progress_cb(20)
            self._check_cancel()
            raw = self.run_solvers(fields)
            self.progress_cb(90)
            self._check_cancel()
            result = self.finalize(raw, fields)
            self._check_cancel()
            self.progress_cb(100)
            for message in records.values():
                if message not in result.warnings:
                    result.warnings.append(message)
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
    """2D compute pipeline backed by ``pipelines.stages_2d`` helpers.

    The three phases delegate to the cfg-only refactor of the legacy
    ``_parse_inputs / _build_fields / _run_solvers / _store_results``
    business logic.  Keeping the helpers in ``pipelines.stages_2d``
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
        # Lazy on purpose (NOT a cycle since the contracts-layer split):
        # importing stages_2d pulls the numba solver chain + JIT warmup;
        # keeping it method-local spares GUI cold-start when no compute runs.
        from sjtu_tpmshx.pipelines.stages_2d import (
            _parse_inputs_cfg, _build_fields_cfg,
        )
        self._parsed = _parse_inputs_cfg(self.cfg)
        return _build_fields_cfg(
            self._parsed,
            live_residuals=self.ui_hooks.get('live_residuals'))

    def run_solvers(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        from sjtu_tpmshx.pipelines.stages_2d import _run_solvers_cfg
        assert self._parsed is not None, (
            "Pipeline2D.run_solvers called before build_fields")
        return _run_solvers_cfg(self._parsed, fields,
                                progress_cb=self.progress_cb,
                                cancel_token=self.cancel,
                                ui_hooks=self.ui_hooks)

    def finalize(self, raw: Dict[str, Any],
                 fields: Dict[str, Any]) -> ComputeResult:
        from sjtu_tpmshx.pipelines.stages_2d import _finalize_cfg
        assert self._parsed is not None, (
            "Pipeline2D.finalize called before build_fields")
        return _finalize_cfg(raw, self._parsed)


class Pipeline3D(ComputePipeline):
    """3D compute pipeline backed by ``pipelines.stages_3d`` helpers.

    The 3D path has no separate build phase — the cfg dict from
    ``_parse_inputs_3d_cfg`` is consumed directly by ``_run_3d_stack``.
    We keep the ABC's 3-phase contract by routing ``build_fields`` to a
    passthrough and caching the parsed dict on ``self._parsed`` so
    finalize can reach ``compute_cfg`` + ``extrap_reasons``.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parsed: Optional[Dict[str, Any]] = None

    def build_fields(self) -> Dict[str, Any]:
        # Lazy on purpose — see Pipeline2D.build_fields.
        from sjtu_tpmshx.pipelines.stages_3d import (
            _parse_inputs_3d_cfg, _build_fields_3d_cfg,
        )
        self._parsed = _parse_inputs_3d_cfg(self.cfg)
        return _build_fields_3d_cfg(self._parsed)

    def run_solvers(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        from sjtu_tpmshx.pipelines.stages_3d import _run_solvers_3d_cfg
        assert self._parsed is not None, (
            "Pipeline3D.run_solvers called before build_fields")
        return _run_solvers_3d_cfg(self._parsed, fields,
                                    progress_cb=self.progress_cb,
                                    cancel_token=self.cancel,
                                    iter_cb=self.ui_hooks.get('iter_cb'))

    def finalize(self, raw: Dict[str, Any],
                 fields: Dict[str, Any]) -> ComputeResult:
        from sjtu_tpmshx.pipelines.stages_3d import _finalize_3d_cfg
        assert self._parsed is not None, (
            "Pipeline3D.finalize called before build_fields")
        return _finalize_3d_cfg(raw, self._parsed)


def pipeline_for(cfg: ComputeConfig,
                 progress_cb: Optional[ProgressFn] = None,
                 cancel_token: Optional[Any] = None,
                 ui_hooks: Optional[Dict[str, Any]] = None) -> ComputePipeline:
    """Dim-dispatch factory: return :class:`Pipeline3D` if ``cfg.is_3d``,
    otherwise :class:`Pipeline2D`.

    Convenience wrapper for adapters / scripts that do not know upfront
    whether the cfg represents a 2D or 3D run.
    """
    cls = Pipeline3D if cfg.is_3d else Pipeline2D
    return cls(cfg, progress_cb=progress_cb, cancel_token=cancel_token,
               ui_hooks=ui_hooks)


__all__ = [
    'ComputeResult',
    'ComputePipeline',
    'Pipeline2D',
    'Pipeline3D',
    'CancelledError',
    'pipeline_for',
]
