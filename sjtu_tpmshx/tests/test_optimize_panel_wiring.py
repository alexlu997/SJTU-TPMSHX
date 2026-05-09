"""End-to-end UI wiring smoke for the Optimize tab.

Verifies the path:
  user clicks Optimize button
    → window._run_optimize(self)
    → ui.optimize_panel.run_optimize(window)
    → _gather_cfg(window) reads UI line-edits
    → _make_worker_class()(cfg, n_init, n_iter, q_batch, seed, save_dir)
    → worker.run() invokes run_qnehvi(..., n_jobs=q_batch)

We don't launch a real Qt window; we build a minimal duck-typed `window`
with the line-edits + combos that _gather_cfg reads. The actual BO is
NOT executed — we instead patch run_qnehvi to capture its kwargs and
return a synthetic Pareto, so the test runs in <1 s.
"""
from __future__ import annotations

import os
import types
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from PySide6.QtWidgets import QLineEdit, QComboBox

from ui.optimize_panel import _gather_cfg, _make_worker_class


# ─── Fake window builder ───────────────────────────────────────────


def _le(text: str) -> QLineEdit:
    le = QLineEdit()
    le.setText(text)
    return le


def _combo(items, default_idx=0) -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setCurrentIndex(default_idx)
    return c


def _make_window():
    """Minimal duck-typed window mirroring the keys _gather_cfg expects."""
    w = types.SimpleNamespace()
    # Geometry (Shanghai HX)
    w.le_L     = _le('0.182')
    w.le_H     = _le('0.042')
    w.le_Lz    = _le('0.042')
    # TPMS seed values (not directly used as cfg keys; informational)
    w.le_Lcell = _le('6.0')
    w.le_t     = _le('0.4')
    w.le_ks    = _le('16.0')
    w.le_uA    = _le('5.0')
    w.le_uB    = _le('5.0')
    w.le_PinA  = _le('192362.0')
    w.le_PinB  = _le('101325.0')
    w.le_TinA  = _le('422.0')
    w.le_TinB  = _le('322.0')
    w.le_rho_s = _le('7900.0')
    w.combo_tpms = _combo(['Diamond', 'Gyroid'], default_idx=0)
    # Fluid combos read by _gather_cfg
    w.combo_fluidA = _combo(['Air', 'Water'], default_idx=0)
    w.combo_fluidB = _combo(['Air', 'Water'], default_idx=1)
    # Optional checkbox + temp converter (skip — _gather_cfg has guards)
    return w


# ─── Tests ─────────────────────────────────────────────────────────


def test_gather_cfg_reads_geometry_from_UI():
    """_gather_cfg must read le_L/le_H/le_Lz into L_domain/H_domain/Lz."""
    w = _make_window()
    cfg = _gather_cfg(w)
    assert cfg['L_domain'] == pytest.approx(0.182)
    assert cfg['H_domain'] == pytest.approx(0.042)
    assert cfg['Lz']       == pytest.approx(0.042)


def test_gather_cfg_reads_velocities_and_pressures():
    w = _make_window()
    cfg = _gather_cfg(w)
    assert cfg['u_A']  == pytest.approx(5.0)
    assert cfg['u_B']  == pytest.approx(5.0)
    assert cfg['P_inA'] == pytest.approx(192362.0)
    assert cfg['P_inB'] == pytest.approx(101325.0)


def test_gather_cfg_reads_solid_density_not_default():
    """Regression for the v1 bug where rho_s was silently dropped and
    optimizer used 2700 (Al) regardless of UI input."""
    w = _make_window()
    cfg = _gather_cfg(w)
    assert cfg['rho_s'] == pytest.approx(7900.0)


def test_gather_cfg_reads_tpms_type():
    w = _make_window()
    cfg = _gather_cfg(w)
    assert cfg['tpms_type'] == 'Diamond'


def test_worker_class_constructible_with_cfg():
    """Worker must instantiate without exception given the gathered cfg."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=4, n_iter=1, q_batch=2,
                    seed=42, save_dir='opt_runs/_test_worker_smoke')
    assert worker.cfg is cfg
    assert worker.n_init == 4
    assert worker.n_iter == 1
    assert worker.q_batch == 2


def test_worker_passes_n_jobs_to_run_qnehvi():
    """Phase 1 wiring fix — worker.run() must pass n_jobs to enable inner
    joblib parallelism (was missing pre-2026-05-09; UI ran sequentially)."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=4,
                    seed=0, save_dir='opt_runs/_test_n_jobs_smoke')

    captured: dict = {}

    def _fake_run_qnehvi(**kwargs):
        captured.update(kwargs)
        # Synthetic 1-pt Pareto so finished_with_result has something
        return {
            'X':         np.zeros((1, 16)),
            'F':         np.array([[-8000.0, 12000.0]]),
            'history_X': np.zeros((1, 16)),
            'history_F': np.array([[-8000.0, 12000.0]]),
            'n_evals':   2,
            'save_dir':  worker.save_dir,
        }

    with patch('optimization.optimizer_qnehvi.run_qnehvi', _fake_run_qnehvi):
        worker.run()

    assert 'n_jobs' in captured, \
        "Worker did not pass n_jobs to run_qnehvi — UI inner parallel disabled"
    assert captured['n_jobs'] >= 1
    assert captured['n_jobs'] <= captured['q_batch']
    assert captured['q_batch'] == 4


def test_worker_n_jobs_capped_at_q_batch():
    """If cfg sets n_jobs > q_batch, the worker must clamp down (joblib
    can't usefully parallelize more than the batch size)."""
    w = _make_window()
    cfg = _gather_cfg(w)
    cfg['n_jobs'] = 32  # absurdly high
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=2,
                    seed=0, save_dir='opt_runs/_test_n_jobs_cap')

    captured: dict = {}

    def _fake_run_qnehvi(**kwargs):
        captured.update(kwargs)
        return {
            'X': np.zeros((0, 16)), 'F': np.zeros((0, 2)),
            'history_X': np.zeros((0, 16)), 'history_F': np.zeros((0, 2)),
            'n_evals': 0, 'save_dir': worker.save_dir,
        }

    with patch('optimization.optimizer_qnehvi.run_qnehvi', _fake_run_qnehvi):
        worker.run()

    assert captured['n_jobs'] == 2  # capped to q_batch


def test_worker_emits_finished_signal_on_success():
    """Run() must emit finished_with_result on the synthetic Pareto."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=2,
                    seed=0, save_dir='opt_runs/_test_finish_smoke')

    received: list = []
    worker.finished_with_result.connect(lambda res: received.append(res))

    def _fake_run_qnehvi(**_kw):
        return {
            'X':         np.array([[6.0]*16]),
            'F':         np.array([[-7500.0, 11000.0]]),
            'history_X': np.array([[6.0]*16]),
            'history_F': np.array([[-7500.0, 11000.0]]),
            'n_evals':   2,
            'save_dir':  worker.save_dir,
        }

    with patch('optimization.optimizer_qnehvi.run_qnehvi', _fake_run_qnehvi):
        worker.run()

    assert len(received) == 1
    assert received[0]['n_evals'] == 2
    assert len(received[0]['X']) == 1


def test_worker_emits_error_signal_on_exception():
    """run_qnehvi raising must NOT crash the worker — must emit error_signal."""
    w = _make_window()
    cfg = _gather_cfg(w)
    Worker = _make_worker_class()
    worker = Worker(cfg=cfg, n_init=2, n_iter=0, q_batch=2,
                    seed=0, save_dir='opt_runs/_test_error_smoke')

    errors: list = []
    worker.error_signal.connect(lambda msg: errors.append(msg))

    def _fake_raise(**_kw):
        raise RuntimeError("synthetic BO crash")

    with patch('optimization.optimizer_qnehvi.run_qnehvi', _fake_raise):
        worker.run()

    assert len(errors) == 1
    assert "RuntimeError" in errors[0]
    assert "synthetic BO crash" in errors[0]
