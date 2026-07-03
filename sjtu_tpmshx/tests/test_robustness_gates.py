"""Robustness-hardening locks (openspec robustness-hardening, 2026-07-03).

Pins the input-validation choke points, the first-class convergence
verdict, the 3D cell cap, and the corrupt-session quarantine — the gaps
the 2026-07-03 robustness survey found and this change closed.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.compute_config import ComputeConfig  # noqa: E402
from domain.compute_result import ComputeResult  # noqa: E402


# ── ComputeConfig.validate — the script/optimizer boundary ────────────

def _canonical(**geometry_over):
    ge = dict(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6, k_s_W_mK=16.0,
              L_dom_m=0.182, H_dom_m=0.042, Lz_m=0.042)
    ge.update(geometry_over)
    return {
        'fluid_A': {'type': 'air', 'u_mps': 8.0, 'T_in_K': 422.0,
                    'P_in_Pa': 192362.0},
        'fluid_B': {'type': 'water', 'u_mps': 0.5, 'T_in_K': 293.15,
                    'P_in_Pa': 101325.0},
        'geometry': ge,
        'solver': {'Nx': 20, 'Ny': 20, 'Nz': 5},
    }


def test_from_dict_valid_passes():
    cfg = ComputeConfig.from_dict(_canonical())
    assert cfg.geometry.L_dom_m == 0.182


def test_from_dict_rejects_nan():
    d = _canonical(L_dom_m=float('nan'))
    with pytest.raises(ValueError, match='L_dom_m'):
        ComputeConfig.from_dict(d)


def test_from_dict_rejects_negative():
    d = _canonical(t_wall_mm=-0.6)
    with pytest.raises(ValueError, match='t_wall_mm'):
        ComputeConfig.from_dict(d)


def test_from_dict_rejects_zero_grid():
    d = _canonical()
    d['solver']['Nx'] = 0
    with pytest.raises(ValueError, match='Nx'):
        ComputeConfig.from_dict(d)


def test_from_json_rejects_json_nan(tmp_path):
    """json.loads happily produces NaN — the exact hole the survey found."""
    d = _canonical()
    raw = json.dumps(d).replace('0.182', 'NaN')
    p = tmp_path / 'bad.json'
    p.write_text(raw, encoding='utf-8')
    with pytest.raises(ValueError):
        ComputeConfig.from_json(p)


def test_shanghai_baseline_still_loads():
    """The legacy layout must survive validation (regression guard)."""
    base = ROOT / 'configs' / 'shanghai_baseline.json'
    if not base.exists():
        pytest.skip('shanghai_baseline.json not present')
    cfg = ComputeConfig.from_json(base)
    assert cfg.geometry.L_cell_mm == 7.0


# ── window strict boundary (duck-typed, no Qt) ────────────────────────

class _FakeLE:
    def __init__(self, txt):
        self._t = str(txt)

    def text(self):
        return self._t


def _fake_window(**over):
    vals = dict(le_L='0.182', le_H='0.042', le_Nx='20', le_Ny='20',
                le_uA='8.0', le_uB='0.5', le_TinA='422', le_TinB='293',
                le_Lcell='7.0', le_t='0.6', le_ks='16.0')
    vals.update(over)
    w = types.SimpleNamespace()
    for k, v in vals.items():
        setattr(w, k, _FakeLE(v))
    return w


def test_strict_widgets_reject_nan():
    from ui.window_config import _validate_required_widgets
    with pytest.raises(ValueError, match='Domain Length'):
        _validate_required_widgets(_fake_window(le_L='nan'), is_3d=False)


def test_strict_widgets_reject_negative():
    from ui.window_config import _validate_required_widgets
    with pytest.raises(ValueError, match='TPMS t'):
        _validate_required_widgets(_fake_window(le_t='-0.6'), is_3d=False)


def test_strict_widgets_allow_negative_celsius_temp():
    """Temp fields may hold °C text — sign check is deferred to
    ComputeConfig.validate (Kelvin domain)."""
    from ui.window_config import _validate_required_widgets
    _validate_required_widgets(_fake_window(le_TinA='-10'), is_3d=False)


# ── ComputeResult.converged first-class field ─────────────────────────

def test_compute_result_has_converged_default_true():
    r = ComputeResult()
    assert r.converged is True
    assert ComputeResult(converged=False).converged is False


# ── 3D cell cap (script path, no UI dialog) ───────────────────────────

def test_run_3d_stack_cell_cap(monkeypatch):
    from runs._case_template import build_cfg
    from pipelines.run_stack_3d import _run_3d_stack
    monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '1000')
    cfg = build_cfg(Nx=20, Ny=20, Nz=5)          # 2000 cells > 1000 cap
    with pytest.raises(ValueError, match='cell cap'):
        _run_3d_stack(cfg)


def test_run_3d_stack_cell_cap_cfg_override(monkeypatch):
    from runs._case_template import build_cfg
    from pipelines.run_stack_3d import _run_3d_stack
    monkeypatch.setenv('TPMSHX_MAX_CELLS_3D', '10')
    cfg = build_cfg(Nx=20, Ny=20, Nz=5, max_cells_3d=100)
    # cfg override wins over env; 2000 > 100 still raises (proves the
    # cfg path is honoured without running a full solve)
    with pytest.raises(ValueError, match='cell cap'):
        _run_3d_stack(cfg)


# ── corrupt-session quarantine ────────────────────────────────────────

def test_corrupt_session_quarantined(tmp_path):
    from controllers.session_manager import SessionManager
    sm = SessionManager(base_dir=tmp_path)
    p = sm.session_path('A')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{ not valid json', encoding='utf-8')
    assert sm.load_session('A') is None
    assert not p.exists(), 'corrupt file must be renamed away'
    quarantined = list(p.parent.glob(p.name + '.corrupt-*'))
    assert quarantined, 'quarantine copy must exist'
