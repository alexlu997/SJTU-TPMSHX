from __future__ import annotations
import types
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QLineEdit, QComboBox, QCheckBox

from ui.quick_design_panel import _gather_inputs, _make_worker_class

def _le(t): le=QLineEdit(); le.setText(t); return le
def _combo(items,i=0): c=QComboBox(); c.addItems(items); c.setCurrentIndex(i); return c

def _make_window(mode="auto"):
    w = types.SimpleNamespace()
    w.le_qd_file = _le("spec.xlsx")
    w.combo_qd_mode = _combo(["auto","fixed"], 0 if mode=="auto" else 1)
    w.combo_qd_arr = _combo(["counter","cross"], 0)
    w.le_qd_rho = _le("7900")
    w.le_qd_topo = _le("Diamond,Gyroid")
    w.le_qd_l = _le("5,6,7,8")
    w.le_qd_t = _le("0.4,0.5")
    w.chk_qd_refine = QCheckBox(); w.chk_qd_refine.setChecked(False)
    w.combo_qd_cell_topo = _combo(["Diamond","Gyroid"], 0)
    w.le_qd_cell_l = _le("7")
    w.le_qd_cell_t = _le("0.5")
    return w

def test_gather_inputs_auto():
    p = _gather_inputs(_make_window("auto"))
    assert p["file"] == "spec.xlsx"
    assert p["mode"] == "auto" and p["arrangement"] == "counter"
    assert p["rho_s"] == 7900.0
    assert p["nodes"] == {"topo":["Diamond","Gyroid"],"l":[5.0,6.0,7.0,8.0],"t":[0.4,0.5]}
    assert p["refine"] is False

def test_gather_inputs_fixed():
    p = _gather_inputs(_make_window("fixed"))
    assert p["mode"] == "fixed"
    assert p["cell"] == ("Diamond", 7.0, 0.5)

def test_worker_auto_calls_backend_and_emits():
    w = _make_window("auto"); p = _gather_inputs(w)
    Worker = _make_worker_class()
    worker = Worker(p)
    captured = {}
    class _D:
        feasible=True; topo="Diamond"; l=5.0; t=0.5; s=0.133; Lx=0.011
        V=2.02e-4; weight=0.6; dP_hot_max=0.005; dP_cold_max=0.031
        T_out_hot_max=560.0; arrangement="counter"; reason=""
    def _fake_load(path): captured["path"]=path; return ["case1"]
    def _fake_enum(cases, arrangement, nodes, rho_s, n_jobs=1, k_s=16.0):
        captured.update(arr=arrangement, nodes=nodes, rho=rho_s, jobs=n_jobs, ks=k_s)
        d=_D(); return [d], d
    received=[]
    worker.finished_with_result.connect(lambda r: received.append(r))
    with patch("design.cases.load_cases", _fake_load), \
         patch("design.select.enumerate_select", _fake_enum):
        worker.run()
    assert captured["path"]=="spec.xlsx"
    assert captured["arr"]=="counter" and captured["rho"]==7900.0
    assert captured["jobs"]==-1   # UI auto 默认全核并行
    assert captured["ks"]==16.0   # 默认 304SS 热导率传入后端
    assert len(received)==1
    feas, best = received[0]["feasible"], received[0]["best"]
    assert best.topo=="Diamond" and len(feas)==1

def test_worker_emits_error_on_exception():
    w=_make_window("auto"); worker=_make_worker_class()(_gather_inputs(w))
    errs=[]; worker.error_signal.connect(lambda m: errs.append(m))
    def _boom(path): raise RuntimeError("bad file")
    with patch("design.cases.load_cases", _boom):
        worker.run()
    assert len(errs)==1 and "RuntimeError" in errs[0]
