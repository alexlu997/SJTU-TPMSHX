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


def build_quick_design_dialog(parent=None):
    """构建并返回快速设计 QDialog。

    对话框实例即是 run_quick_design(window) 所期望的 duck-typed 'window'：
    所有合约属性 (le_qd_*, combo_qd_*, chk_qd_refine, _qd_table, _qd_status)
    直接附加在对话框对象上。

    调用方式::

        dlg = build_quick_design_dialog(parent=self)
        dlg.show()
    """
    # ── 延迟导入 Qt (保持模块可在非 GUI 环境导入) ──────────────
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
        QGroupBox, QLabel, QLineEdit, QPushButton,
        QComboBox, QCheckBox, QTableWidget, QFileDialog,
        QSizePolicy, QFrame,
    )
    from PySide6.QtCore import Qt

    dlg = QDialog(parent)
    dlg.setWindowTitle("快速设计工具")
    dlg.resize(800, 680)
    dlg.setMinimumSize(640, 520)

    root = QVBoxLayout(dlg)
    root.setContentsMargins(14, 12, 14, 12)
    root.setSpacing(8)

    # ── 工况文件选择 ──────────────────────────────────────────
    file_row = QHBoxLayout()
    file_row.setSpacing(6)
    lbl_file = QLabel("工况文件:")
    file_row.addWidget(lbl_file)
    le_file = QLineEdit()
    le_file.setPlaceholderText("选择 .xlsx / .csv 工况文件…")
    le_file.setReadOnly(False)
    file_row.addWidget(le_file, 1)
    btn_browse = QPushButton("浏览…")
    btn_browse.setFixedWidth(68)

    def _browse():
        path, _ = QFileDialog.getOpenFileName(
            dlg, "选择工况文件", "",
            "工况 (*.xlsx *.csv);;所有文件 (*)")
        if path:
            le_file.setText(path)

    btn_browse.clicked.connect(_browse)
    file_row.addWidget(btn_browse)
    root.addLayout(file_row)

    # ── 模式 / 排列 ──────────────────────────────────────────
    mode_row = QHBoxLayout()
    mode_row.setSpacing(16)

    mode_row.addWidget(QLabel("模式:"))
    combo_mode = QComboBox()
    combo_mode.addItems(["auto", "fixed"])
    combo_mode.setFixedWidth(100)
    mode_row.addWidget(combo_mode)

    mode_row.addSpacing(16)
    mode_row.addWidget(QLabel("排列:"))
    combo_arr = QComboBox()
    combo_arr.addItems(["counter", "cross"])
    combo_arr.setFixedWidth(100)
    mode_row.addWidget(combo_arr)

    mode_row.addSpacing(16)
    mode_row.addWidget(QLabel("材料密度 (kg/m³):"))
    le_rho = QLineEdit("7900")
    le_rho.setFixedWidth(80)
    mode_row.addWidget(le_rho)

    mode_row.addStretch(1)
    root.addLayout(mode_row)

    # ── Auto 参数组 ───────────────────────────────────────────
    auto_group = QGroupBox("自动搜索参数")
    auto_form = QFormLayout(auto_group)
    auto_form.setSpacing(6)

    le_topo = QLineEdit("Diamond,Gyroid")
    le_topo.setToolTip("拓扑列表，逗号分隔")
    auto_form.addRow("拓扑 (topo):", le_topo)

    le_l = QLineEdit("5,6,7,8")
    le_l.setToolTip("胞元尺寸 l (mm) 列表，逗号分隔")
    auto_form.addRow("l 列表 (mm):", le_l)

    le_t = QLineEdit("0.4,0.5")
    le_t.setToolTip("壁厚 t (mm) 列表，逗号分隔")
    auto_form.addRow("t 列表 (mm):", le_t)

    chk_refine = QCheckBox("warm-start 精细化最优解")
    auto_form.addRow("精细化:", chk_refine)

    root.addWidget(auto_group)

    # ── Fixed 参数组 ──────────────────────────────────────────
    fixed_group = QGroupBox("固定胞元参数")
    fixed_form = QFormLayout(fixed_group)
    fixed_form.setSpacing(6)

    combo_cell_topo = QComboBox()
    combo_cell_topo.addItems(["Diamond", "Gyroid"])
    fixed_form.addRow("拓扑:", combo_cell_topo)

    le_cell_l = QLineEdit("7")
    le_cell_l.setToolTip("胞元尺寸 l (mm)")
    fixed_form.addRow("l (mm):", le_cell_l)

    le_cell_t = QLineEdit("0.5")
    le_cell_t.setToolTip("壁厚 t (mm)")
    fixed_form.addRow("t (mm):", le_cell_t)

    root.addWidget(fixed_group)

    # ── 初始可见性 & 切换 ─────────────────────────────────────
    fixed_group.setVisible(False)   # 默认 auto 模式

    def _on_mode_changed(text):
        is_auto = (text == "auto")
        auto_group.setVisible(is_auto)
        fixed_group.setVisible(not is_auto)

    combo_mode.currentTextChanged.connect(_on_mode_changed)

    # ── 操作按钮行 ────────────────────────────────────────────
    btn_row = QHBoxLayout()
    btn_run = QPushButton("▶ 运行设计")
    btn_run.setMinimumWidth(120)
    btn_run.clicked.connect(lambda: run_quick_design(dlg))
    btn_row.addWidget(btn_run)

    btn_export = QPushButton("导出 xlsx")
    btn_export.setMinimumWidth(90)

    def _export():
        last = getattr(dlg, "_qd_last", None)
        if last is None:
            dlg._qd_status.setText("无结果可导出")
            return
        feas = last.get("feasible", [])
        if not feas:
            dlg._qd_status.setText("无可行件可导出")
            return
        path, _ = QFileDialog.getSaveFileName(
            dlg, "导出可行设计", "quick_design_results.xlsx",
            "Excel (*.xlsx)")
        if not path:
            return
        try:
            import pandas as pd
            from design.select import pareto_tags
            tags_map = pareto_tags(feas)
            rows = []
            for d in sorted(feas, key=lambda x: x.V):
                rows.append({
                    "topo": d.topo,
                    "l": d.l,
                    "t": d.t,
                    "W_mm": round(d.s * 1e3, 1),
                    "H_mm": round(d.s * 1e3, 1),
                    "Lx_mm": round(d.Lx * 1e3, 1),
                    "V_L": round(d.V * 1e3, 4),
                    "weight_kg": round(d.weight, 4),
                    "dP_hot": round(getattr(d, "dP_hot_max", 0), 4),
                    "dP_cold": round(getattr(d, "dP_cold_max", 0), 4),
                    "T_out_hot_max": round(getattr(d, "T_out_hot_max", float("nan")), 2),
                    "tags": ",".join(tags_map.get(id(d), [])),
                })
            pd.DataFrame(rows).to_excel(path, index=False, engine="openpyxl")
            dlg._qd_status.setText(f"已导出 {len(rows)} 条 → {path}")
        except Exception as exc:
            dlg._qd_status.setText(f"导出失败: {exc}")

    btn_export.clicked.connect(_export)
    btn_row.addWidget(btn_export)
    btn_row.addStretch(1)
    root.addLayout(btn_row)

    # ── 结果表 ────────────────────────────────────────────────
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    root.addWidget(sep)

    lbl_results = QLabel("可行设计列表:")
    root.addWidget(lbl_results)

    tbl = QTableWidget(0, 10)
    tbl.setHorizontalHeaderLabels(
        ["拓扑", "l", "t", "W×H(mm)", "Lx(mm)", "V(L)", "重量(kg)",
         "热侧压损%", "冷侧压损%", "标签"])
    tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tbl.horizontalHeader().setStretchLastSection(True)
    tbl.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    root.addWidget(tbl, 1)

    # ── 状态标签 ─────────────────────────────────────────────
    lbl_status = QLabel("就绪")
    lbl_status.setWordWrap(True)
    root.addWidget(lbl_status)

    # ── 绑定合约属性 ──────────────────────────────────────────
    dlg.le_qd_file         = le_file
    dlg.combo_qd_mode      = combo_mode
    dlg.combo_qd_arr       = combo_arr
    dlg.le_qd_rho          = le_rho
    dlg.le_qd_topo         = le_topo
    dlg.le_qd_l            = le_l
    dlg.le_qd_t            = le_t
    dlg.chk_qd_refine      = chk_refine
    dlg.combo_qd_cell_topo = combo_cell_topo
    dlg.le_qd_cell_l       = le_cell_l
    dlg.le_qd_cell_t       = le_cell_t
    dlg._qd_table          = tbl
    dlg._qd_status         = lbl_status

    # ── 测试钩子属性 ─────────────────────────────────────────
    dlg._qd_run_btn    = btn_run
    dlg._qd_auto_group = auto_group
    dlg._qd_fixed_group = fixed_group

    return dlg
