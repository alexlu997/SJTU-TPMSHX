"""ui/quick_design_panel.py — 快速设计面板绑定 (仿 optimize_panel.py)。

自由函数 + lazy QThread worker, 操作 duck-typed window 属性。后端不阻塞 UI。
公开 API: run_quick_design(window) / _gather_inputs(window) / _make_worker_class()。
"""
from __future__ import annotations
import os
from typing import Optional

def _flist(text, cast=float):
    """'5, 6, 7' → [5.0,6.0,7.0]; 空 → []。"""
    return [cast(x) for x in str(text).replace("|", ",").split(",") if x.strip()]

def _gather_inputs(window) -> dict:
    """读面板控件 → dict。缺控件用安全默认 (供测试 duck-typed window)。"""
    def txt(attr, dflt=""):
        w = getattr(window, attr, None)
        return w.text() if (w is not None and hasattr(w, "text")) else dflt
    def cur(attr, dflt=""):
        w = getattr(window, attr, None)
        return w.currentText() if (w is not None and hasattr(w, "currentText")) else dflt
    def chk(attr, dflt=False):
        w = getattr(window, attr, None)
        return bool(w.isChecked()) if (w is not None and hasattr(w, "isChecked")) else dflt

    try:
        rho_s = float(txt("le_qd_rho", "7900"))
    except ValueError:
        rho_s = 7900.0
    return {
        "file": txt("le_qd_file"),
        "mode": cur("combo_qd_mode", "auto"),
        "arrangement": cur("combo_qd_arr", "counter"),
        "rho_s": rho_s,
        "refine": chk("chk_qd_refine"),
        "nodes": {
            "topo": [s.strip() for s in txt("le_qd_topo", "Diamond,Gyroid").split(",") if s.strip()],
            "l": _flist(txt("le_qd_l", "5,6,7,8")),
            "t": _flist(txt("le_qd_t", "0.4,0.5")),
        },
        "cell": (cur("combo_qd_cell_topo", "Diamond"),
                 float(txt("le_qd_cell_l", "7") or 7),
                 float(txt("le_qd_cell_t", "0.5") or 0.5)),
    }

def _make_worker_class():
    """lazy QThread worker (Qt import 延迟, 非 GUI 工具可 import 本模块)。"""
    from PySide6.QtCore import QThread, Signal

    class _QDWorker(QThread):
        finished_with_result = Signal(object)   # {"feasible":[Design],"best":Design|None,"params":dict}
        error_signal = Signal(str)

        def __init__(self, params):
            super().__init__()
            self.params = params

        def run(self):
            try:
                from design.cases import load_cases
                from design.sizing import size_fixed_cell
                from design.select import enumerate_select
                p = self.params
                cases = load_cases(p["file"])
                if p["mode"] == "fixed":
                    topo, l, t = p["cell"]
                    d = size_fixed_cell(cases, topo, l, t, p["arrangement"], rho_s=p["rho_s"])
                    feas = [d] if d.feasible else []
                    best = d if d.feasible else None
                else:
                    feas, best = enumerate_select(cases, p["arrangement"], p["nodes"], rho_s=p["rho_s"])
                    if p["refine"] and best is not None:
                        from design.optimize import warm_start_joint
                        ref = warm_start_joint(cases, best, p["arrangement"], rho_s=p["rho_s"])
                        if ref is not best and ref.feasible:
                            feas = list(feas) + [ref]
                            if ref.V < best.V:
                                best = ref
                self.finished_with_result.emit({"feasible": feas, "best": best, "params": p})
            except Exception as e:
                self.error_signal.emit(f"{type(e).__name__}: {e}")

    return _QDWorker

def _set_status(window, text):
    t = getattr(window, "_qd_status", None)
    if t is not None and hasattr(t, "setText"):
        try: t.setText(text); return
        except Exception: pass
    print(f"[quick-design] {text}")

def _fill_table(window, feasible, best):
    """把可行件按 V 排序填进 window._qd_table (QTableWidget)。无表则打印。"""
    rows = sorted(feasible, key=lambda d: d.V)
    from design.select import pareto_tags
    tags = pareto_tags(feasible)
    tbl = getattr(window, "_qd_table", None)
    if tbl is None or not hasattr(tbl, "setRowCount"):
        for d in rows:
            print(f"  {d.topo} l={d.l} t={d.t} s={d.s*1e3:.1f} Lx={d.Lx*1e3:.1f} "
                  f"V={d.V*1e3:.3f}L wt={d.weight:.3f} dPh={d.dP_hot_max*100:.2f} "
                  f"dPc={d.dP_cold_max*100:.2f} {','.join(tags.get(id(d),[]))}")
        return
    cols = ["拓扑","l","t","W×H(mm)","Lx(mm)","V(L)","重量(kg)","热侧压损%","冷侧压损%","标签"]
    tbl.setColumnCount(len(cols)); tbl.setRowCount(len(rows))
    tbl.setHorizontalHeaderLabels(cols)
    from PySide6.QtWidgets import QTableWidgetItem
    for i, d in enumerate(rows):
        vals = [d.topo, f"{d.l:g}", f"{d.t:g}", f"{d.s*1e3:.0f}×{d.s*1e3:.0f}",
                f"{d.Lx*1e3:.1f}", f"{d.V*1e3:.3f}", f"{d.weight:.3f}",
                f"{d.dP_hot_max*100:.2f}", f"{d.dP_cold_max*100:.2f}",
                ",".join(tags.get(id(d), []))]
        for j, v in enumerate(vals):
            tbl.setItem(i, j, QTableWidgetItem(str(v)))

def run_quick_design(window) -> None:
    """点「运行设计」入口: 后台 worker 跑后端, 完成回填表。"""
    if getattr(window, "_qd_worker", None) is not None and window._qd_worker.isRunning():
        _set_status(window, "设计运行中…"); return
    params = _gather_inputs(window)
    if not params["file"]:
        _set_status(window, "请先选工况文件"); return
    Worker = _make_worker_class()
    worker = Worker(params)

    def _on_done(res):
        feas, best = res["feasible"], res["best"]
        if not feas:
            _set_status(window, "无可行件 (≤450mm)")
        else:
            _fill_table(window, feas, best)
            bt = f"{best.topo} l={best.l:g} t={best.t:g} V={best.V*1e3:.3f}L" if best else "—"
            _set_status(window, f"完成 · {len(feas)} 可行 · min-V: {bt}")
        window._qd_last = res
        window._qd_worker = None

    def _on_err(msg):
        _set_status(window, f"错误: {msg}")
        window._qd_worker = None

    worker.finished_with_result.connect(_on_done)
    worker.error_signal.connect(_on_err)
    window._qd_worker = worker
    _set_status(window, f"运行中 · {params['mode']} · {params['arrangement']} …")
    worker.start()
