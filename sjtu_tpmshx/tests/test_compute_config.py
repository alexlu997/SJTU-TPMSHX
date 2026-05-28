"""Tests for ``controllers/compute_config.py`` — audit C3 dataclass.

Covers:
- Default construction
- ``is_3d`` derived property
- JSON round-trip (canonical schema)
- JSON load from legacy ``configs/shanghai_baseline.json`` layout
- ``from_qt_window`` adapter with a minimal mock window
- Optional-widget tolerance (le_Lz / le_TsInit / combo_fluidB missing)
- K/°C toggle honoured via ``window._temp_to_K``
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional

import pytest

from controllers.compute_config import (
    ComputeConfig,
    FluidConfig,
    GeometryConfig,
    SolverConfig,
)


# ── helpers ──────────────────────────────────────────────────────────


class _StubLineEdit:
    """Tiny stand-in for QLineEdit that returns a fixed text value."""

    def __init__(self, text: str):
        self._text = text

    def text(self) -> str:
        return self._text


class _StubComboBox:
    def __init__(self, text: str):
        self._text = text

    def currentText(self) -> str:
        return self._text


class _StubWindow:
    """Build only the attributes that ``from_qt_window`` reads."""

    def __init__(self, **fields):
        # geometry
        self.combo_tpms = _StubComboBox(fields.get('tpms', 'Diamond'))
        self.le_Lcell = _StubLineEdit(fields.get('Lcell', '8.0'))
        self.le_t = _StubLineEdit(fields.get('t', '0.5'))
        self.le_ks = _StubLineEdit(fields.get('ks', '20.0'))
        self.le_L = _StubLineEdit(fields.get('L', '0.20'))
        self.le_H = _StubLineEdit(fields.get('H', '0.05'))
        if 'Lz' in fields:
            self.le_Lz = _StubLineEdit(fields['Lz'])
        # solver
        self.le_Nx = _StubLineEdit(fields.get('Nx', '40'))
        self.le_Ny = _StubLineEdit(fields.get('Ny', '80'))
        self.le_Nz = _StubLineEdit(fields.get('Nz', '5'))
        if 'TsInit' in fields:
            self.le_TsInit = _StubLineEdit(fields['TsInit'])
        # fluids
        self.combo_fluidA = _StubComboBox(fields.get('fluidA', 'Air'))
        if 'fluidB' in fields:
            self.combo_fluidB = _StubComboBox(fields['fluidB'])
        self.le_uA = _StubLineEdit(fields.get('uA', '10.0'))
        self.le_uB = _StubLineEdit(fields.get('uB', '2.0'))
        self.le_TinA = _StubLineEdit(fields.get('TinA', '400.0'))
        self.le_TinB = _StubLineEdit(fields.get('TinB', '300.0'))
        self.le_PinA = _StubLineEdit(fields.get('PinA', '200000.0'))
        self.le_PinB = _StubLineEdit(fields.get('PinB', '101325.0'))


# ── defaults ─────────────────────────────────────────────────────────


def test_default_compute_config_is_2d():
    cfg = ComputeConfig()
    assert cfg.solver.Nz == 1
    assert cfg.is_3d is False
    assert cfg.fluid_A.type == 'air'
    assert cfg.geometry.tpms == 'Gyroid'


def test_is_3d_triggers_at_nz_2():
    cfg = ComputeConfig()
    cfg.solver.Nz = 1
    assert not cfg.is_3d
    cfg.solver.Nz = 2
    assert cfg.is_3d
    cfg.solver.Nz = 20
    assert cfg.is_3d


# ── JSON round-trip ─────────────────────────────────────────────────


def test_json_roundtrip_canonical():
    cfg = ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=12.3, T_in_K=420.0,
                            P_in_Pa=2e5),
        fluid_B=FluidConfig(type='water', u_mps=0.15, T_in_K=305.0,
                            P_in_Pa=1.5e5),
        geometry=GeometryConfig(tpms='Diamond', L_cell_mm=8.0,
                                t_wall_mm=0.55, k_s_W_mK=18.0,
                                L_dom_m=0.20, H_dom_m=0.05, Lz_m=0.05),
        solver=SolverConfig(Nx=40, Ny=80, Nz=10, T_s_init_K=350.0),
    )
    with tempfile.NamedTemporaryFile('w', suffix='.json',
                                      delete=False) as f:
        path = f.name
    try:
        cfg.to_json(path)
        cfg2 = ComputeConfig.from_json(path)
    finally:
        Path(path).unlink()
    assert cfg2.fluid_A.u_mps == pytest.approx(12.3)
    assert cfg2.fluid_B.type == 'water'
    assert cfg2.geometry.tpms == 'Diamond'
    assert cfg2.geometry.Lz_m == pytest.approx(0.05)
    assert cfg2.solver.Nz == 10
    assert cfg2.solver.T_s_init_K == pytest.approx(350.0)
    assert cfg2.is_3d


def test_json_legacy_shanghai_baseline_layout():
    """``configs/shanghai_baseline.json`` ships with the audit AR8 layout
    (``_meta``/``geometry``/``domain``/``_excluded``).  ``from_json``
    must absorb it; fluids fall back to defaults because the Shanghai
    loop overwrites them per case."""
    legacy = {
        '_meta': {'case_name': 'unit test'},
        'geometry': {
            'tpms': 'Gyroid', 'L_cell_mm': 7.0,
            't_wall_mm': 0.6, 'k_s_W_mK': 16.0,
        },
        'domain': {
            'L_dom_m': 0.182, 'H_dom_m': 0.042, 'Lz_m': 0.042,
        },
    }
    with tempfile.NamedTemporaryFile('w', suffix='.json',
                                      delete=False) as f:
        path = f.name
    try:
        Path(path).write_text(json.dumps(legacy), encoding='utf-8')
        cfg = ComputeConfig.from_json(path)
    finally:
        Path(path).unlink()
    assert cfg.geometry.tpms == 'Gyroid'
    assert cfg.geometry.L_cell_mm == pytest.approx(7.0)
    assert cfg.geometry.L_dom_m == pytest.approx(0.182)
    assert cfg.geometry.Lz_m == pytest.approx(0.042)
    # fluid defaults preserved
    assert cfg.fluid_A.type == 'air'


def test_repo_shanghai_baseline_loads():
    """Sanity: the file checked into ``configs/`` parses cleanly."""
    repo_path = (Path(__file__).resolve().parents[1]
                 / 'configs' / 'shanghai_baseline.json')
    cfg = ComputeConfig.from_json(repo_path)
    assert cfg.geometry.tpms == 'Gyroid'
    assert cfg.geometry.L_cell_mm == pytest.approx(7.0)
    assert cfg.geometry.L_dom_m == pytest.approx(0.182)


# ── from_qt_window adapter ──────────────────────────────────────────


def test_from_qt_window_full_smoke():
    window = _StubWindow(
        tpms='Diamond', Lcell='8.0', t='0.5', ks='20.0',
        L='0.20', H='0.05', Lz='0.05',
        Nx='40', Ny='80', Nz='5',
        fluidA='Air', fluidB='Water',
        uA='10.0', uB='2.0',
        TinA='400.0', TinB='300.0',
        PinA='200000.0', PinB='101325.0',
        TsInit='350.0',
    )
    cfg = ComputeConfig.from_qt_window(window)
    assert cfg.geometry.tpms == 'Diamond'
    assert cfg.geometry.L_cell_mm == pytest.approx(8.0)
    assert cfg.geometry.Lz_m == pytest.approx(0.05)
    assert cfg.solver.Nz == 5
    assert cfg.solver.T_s_init_K == pytest.approx(350.0)
    assert cfg.fluid_A.type == 'air'
    assert cfg.fluid_B.type == 'water'
    assert cfg.fluid_A.u_mps == pytest.approx(10.0)
    assert cfg.fluid_B.P_in_Pa == pytest.approx(101325.0)
    assert cfg.is_3d


def test_from_qt_window_optional_widgets_missing():
    """No le_Lz, no le_TsInit, no combo_fluidB → falls back to defaults
    without raising."""
    window = _StubWindow(
        tpms='Gyroid', Nx='30', Ny='60', Nz='1',
        fluidA='Air',  # combo_fluidB intentionally absent
    )
    # Remove le_Lz / le_TsInit / combo_fluidB to simulate stripped-down UI
    if hasattr(window, 'le_Lz'):
        del window.le_Lz
    cfg = ComputeConfig.from_qt_window(window)
    assert cfg.geometry.Lz_m is None
    assert cfg.solver.T_s_init_K is None
    assert cfg.solver.Nz == 1
    assert cfg.fluid_B.type == 'air'   # default
    assert not cfg.is_3d


def test_from_qt_window_temp_to_K_hook_called():
    """The window's ``_temp_to_K`` hook converts °C → K. The adapter
    must use it instead of raw float()."""
    window = _StubWindow(TinA='100', TinB='50')   # °C if hook present

    def _temp_to_K(widget):
        return float(widget.text()) + 273.15

    window._temp_to_K = _temp_to_K
    cfg = ComputeConfig.from_qt_window(window)
    assert cfg.fluid_A.T_in_K == pytest.approx(373.15)
    assert cfg.fluid_B.T_in_K == pytest.approx(323.15)


def test_from_qt_window_blank_lineedit_uses_default():
    """An empty QLineEdit (user deleted the value) falls back to the
    dataclass default rather than raising."""
    window = _StubWindow(uA='', Nx='', TinA='')
    cfg = ComputeConfig.from_qt_window(window)
    assert cfg.fluid_A.u_mps == 5.0   # FluidConfig default
    assert cfg.solver.Nx == 30        # SolverConfig default
    assert cfg.fluid_A.T_in_K == 300.0
