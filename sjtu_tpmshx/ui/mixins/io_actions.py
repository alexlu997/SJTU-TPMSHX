"""IOActionsMixin — export results / figures, save & load config JSON.

Extracted verbatim from main.py (openspec split-ui-main, 2026-07-03).
Mixed into Main_Menu; methods keep their exact names and behaviour.
``_export_figure`` reads ``__version__`` and ``_git_commit_hash`` as
module globals — both live in ``main`` (which imports us), so they
are resolved lazily here to keep the import graph acyclic (same
pattern as ``ui.mixins.run_history._git_commit_hash``).
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from ui.ui_constants import TOAST_MS_SHORT, TOAST_MS_MED


def _git_commit_hash() -> str:
    """Short commit of the running tree, or ''. Lazy-resolved from ``main``
    so this module never imports ``main`` at load time (``main`` imports us).
    Tries both launch modes: ``python main.py`` / ``python -m sjtu_tpmshx.main``.
    """
    for mod in ("main", "sjtu_tpmshx.main"):
        try:
            return __import__(mod, fromlist=["_git_commit_hash"])._git_commit_hash()
        except Exception:
            continue
    return ""


class _LazyMainVersion:
    """Lazy str proxy for ``main.__version__`` (same acyclic-import
    rationale as ``_git_commit_hash`` above). Supports str() and
    f-string formatting, which is all ``_export_figure`` needs."""

    def _resolve(self) -> str:
        for mod in ("main", "sjtu_tpmshx.main"):
            try:
                return __import__(mod, fromlist=["__version__"]).__version__
            except Exception:
                continue
        return "?"

    def __str__(self) -> str:
        return self._resolve()

    def __format__(self, spec: str) -> str:
        return format(self._resolve(), spec)


__version__ = _LazyMainVersion()


class IOActionsMixin:
    def _export_results(self):
        """Export last compute results to CSV + optional NPZ."""
        import os, csv
        res_3d = getattr(self, '_result_3d', None)
        has_2d = getattr(self, '_has_results_2d', False)
        # 2026-05-20 UI sweep (Tier 14, user re-audit): previously this
        # gate used `_has_results_3d`, which only goes True if the 3D
        # PyVistaQt panel rendered successfully. When the solver
        # succeeded but visualisation failed, the export button was
        # enabled (gated on `_has_results`) yet clicking it landed on
        # the "No Results" dialog because both `has_2d` and `has_3d`
        # were False. Switch to a data-presence check: numerical results
        # are exportable independent of whether the 3D scene rendered.
        has_3d = res_3d is not None
        if not has_2d and not has_3d:
            QMessageBox.information(self, "No Results",
                "Run Compute first to generate exportable results.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "results.csv",
            "CSV (*.csv);;All Files (*)")
        if not path:
            return
        try:
            rows = []
            if res_3d is not None:
                # B3 C5: res_3d is the ComputeResult (raw_3d dict retired).
                # Scalars come off the dataclass / props; arrays off fields.
                _rf = res_3d.fields
                rows.append(["Q [W]", f"{res_3d.Q_W:.4f}"])
                rows.append(["dP_A [Pa]", f"{res_3d.dP_A_Pa:.2f}"])
                rows.append(["dP_B [Pa]", f"{res_3d.dP_B_Pa:.2f}"])
                rows.append(["T_inA [K]",
                             f"{res_3d.props.get('T_in_A_K', 0) or 0:.2f}"])
                rows.append(["u_A [m/s]",
                             f"{res_3d.props.get('u_A_in_mps', 0) or 0:.4f}"])
                Ta = _rf.get('Ta')
                if Ta is not None:
                    rows.append(["Ta_min [K]", f"{float(Ta.min()):.2f}"])
                    rows.append(["Ta_max [K]", f"{float(Ta.max()):.2f}"])
                    rows.append(["Grid Nx", str(Ta.shape[0])])
                    rows.append(["Grid Ny", str(Ta.shape[1])])
                    rows.append(["Grid Nz", str(Ta.shape[2])])
                rows.append(["Lx [m]", f"{_rf.get('Lx', 0) or 0:.6f}"])
                rows.append(["Ly [m]", f"{_rf.get('Ly', 0) or 0:.6f}"])
                rows.append(["Lz [m]", f"{_rf.get('Lz', 0) or 0:.6f}"])
            with open(path, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(["Parameter", "Value"])
                w.writerows(rows)
            # Optional: save 3D fields as NPZ alongside. Keep the legacy
            # NPZ schema (vmag, P_kPa) stable: map from ComputeResult.fields
            # (vmag_A → vmag; P_fA/1000 → P_kPa).
            npz_path = os.path.splitext(path)[0] + '_fields.npz'
            if res_3d is not None:
                _rf = res_3d.fields
                save_dict = {}
                for npz_key, src in (('Ta', 'Ta'), ('Tb', 'Tb'),
                                     ('Ts', 'Ts'), ('vmag', 'vmag_A'),
                                     ('L_mm', 'L_mm'), ('dx', 'dx'),
                                     ('dy', 'dy'), ('dz', 'dz')):
                    v = _rf.get(src)
                    if v is not None:
                        save_dict[npz_key] = v
                _p_fa = _rf.get('P_fA')
                if _p_fa is not None:
                    save_dict['P_kPa'] = _p_fa / 1000.0
                if save_dict:
                    import numpy as _np_exp
                    _np_exp.savez_compressed(npz_path, **save_dict)
            self.statusBar().showMessage(f"Exported: {path}", TOAST_MS_MED)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    # ─────────────────────────────────────────────────────────
    #  Save / Load configuration
    # ─────────────────────────────────────────────────────────
    def save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config", "SJTU-TPMSHX_config.json",
            "JSON Files (*.json)")
        if not path:
            return
        cfg = {
            # Domain
            "L":         self.le_L.text(),
            "H":         self.le_H.text(),
            # Solid
            "rho_s":     self.le_rho_s.text(),
            "Nx":        self.le_Nx.text(),
            "Ny":        self.le_Ny.text(),
            # TPMS
            "tpms_type": self.combo_tpms.currentText(),
            "L_cell":    self.le_Lcell.text(),
            "t":         self.le_t.text(),
            "k_s":       self.le_ks.text(),
            # Solid initial temperature (optional; empty = legacy seed)
            "T_s_init":  self.le_TsInit.text() if hasattr(self, 'le_TsInit') else "",
            # Fluid A
            "u_A":       self.le_uA.text(),
            "T_inA":     self.le_TinA.text(),
            "P_inA":     self.le_PinA.text(),
            # Fluid B
            "u_B":       self.le_uB.text(),
            "T_inB":     self.le_TinB.text(),
            "P_inB":     self.le_PinB.text(),
            # Direction & pipe geometry
            "dir_A": self.combo_dirA.currentIndex(),
            "dir_B": self.combo_dirB.currentIndex(),
            "pipeA_in_ctr":  self.le_pipeA_in_ctr.text(),
            "pipeA_in_w":    self.le_pipeA_in_w.text(),
            "pipeA_out_ctr": self.le_pipeA_out_ctr.text(),
            "pipeA_out_w":   self.le_pipeA_out_w.text(),
            #"transA": removed (full-domain solve)
            "pipeB_in_ctr":  self.le_pipeB_in_ctr.text(),
            "pipeB_in_w":    self.le_pipeB_in_w.text(),
            "pipeB_out_ctr": self.le_pipeB_out_ctr.text(),
            "pipeB_out_w":   self.le_pipeB_out_w.text(),
            #"transB": removed (full-domain solve)
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", "",
            "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e)); return

        def _set(le, key):
            if key in cfg: le.setText(str(cfg[key]))

        _set(self.le_L,        "L")
        _set(self.le_H,        "H")
        _set(self.le_rho_s,    "rho_s")
        _set(self.le_Nx,       "Nx")
        _set(self.le_Ny,       "Ny")
        _set(self.le_Lcell,    "L_cell")
        _set(self.le_t,        "t")
        _set(self.le_ks,       "k_s")
        _set(self.le_uA,       "u_A")
        _set(self.le_TinA,     "T_inA")
        _set(self.le_PinA,     "P_inA")
        _set(self.le_uB,       "u_B")
        _set(self.le_TinB,     "T_inB")
        _set(self.le_PinB,     "P_inB")
        if hasattr(self, 'le_TsInit'):
            _set(self.le_TsInit, "T_s_init")
        # Pipe geometry
        _set(self.le_pipeA_in_ctr,  "pipeA_in_ctr")
        _set(self.le_pipeA_in_w,    "pipeA_in_w")
        _set(self.le_pipeA_out_ctr, "pipeA_out_ctr")
        _set(self.le_pipeA_out_w,   "pipeA_out_w")
        # transA/B removed (full-domain solve)
        _set(self.le_pipeB_in_ctr,  "pipeB_in_ctr")
        _set(self.le_pipeB_in_w,    "pipeB_in_w")
        _set(self.le_pipeB_out_ctr, "pipeB_out_ctr")
        _set(self.le_pipeB_out_w,   "pipeB_out_w")
        # (see above)

        if "tpms_type" in cfg:
            idx = self.combo_tpms.findText(cfg["tpms_type"])
            if idx >= 0: self.combo_tpms.setCurrentIndex(idx)
        if "dir_A" in cfg:
            self.combo_dirA.setCurrentIndex(int(cfg["dir_A"]))
        if "dir_B" in cfg:
            self.combo_dirB.setCurrentIndex(int(cfg["dir_B"]))

    def _copy_figure_clipboard(self):
        """Copy the currently active canvas image to the system clipboard
        (ui-batch4 ③) — one click from result plot to WeChat / PPT.
        widget.grab() = what's on screen (theme background included); the
        high-fidelity path stays the PNG export."""
        tab = getattr(self, '_active_tab', None)
        if tab == '2d_view':
            tab = self._resolve_2d_view_card()
        canvas = {'temp': getattr(self, 'canvas_temp', None),
                  'pres': getattr(self, 'canvas_pres', None),
                  'vel': getattr(self, 'canvas_vel', None),
                  'layout': getattr(self, 'canvas_layout', None),
                  'pareto': getattr(self, 'canvas_pareto', None)}.get(tab)
        if canvas is None or tab not in getattr(self, '_drawn_tabs', set()):
            self.statusBar().showMessage("当前无可复制的图像 — 请先计算或预览。",
                                         TOAST_MS_SHORT)
            return
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setImage(canvas.grab().toImage())
        self.statusBar().showMessage(f"已复制 {tab} 图像到剪贴板。", TOAST_MS_SHORT)

    def _export_figure(self):
        """Export a chosen figure to PNG/SVG/PDF with user-selected DPI
        and embedded reproducibility metadata (preset, commit, timestamp,
        grid). Pops a 2-step picker: figure → format/DPI → save path."""
        all_items = [("温度", 'temp'), ("压力", 'pres'),
                     ("速度", 'vel'), ("几何布局", 'layout'),
                     ("Pareto / 优化", 'pareto')]
        tab_canvas = {'temp': self.canvas_temp, 'pres': self.canvas_pres,
                      'vel': self.canvas_vel, 'layout': self.canvas_layout,
                      'pareto': self.canvas_pareto}
        drawn = getattr(self, '_drawn_tabs', set())
        items = [name for name, key in all_items if key in drawn]
        tab_keys = [key for name, key in all_items if key in drawn]
        if not items:
            self.statusBar().showMessage("No figures to export yet.", TOAST_MS_SHORT)
            return
        choice, ok = QInputDialog.getItem(
            self, "Export Figure", "Select figure to export:",
            items, 0, False)
        if not ok:
            return
        key = tab_keys[items.index(choice)]
        canvas = tab_canvas[key]

        # DPI picker — common research-paper presets.
        dpi_items = ["150 (screen)", "300 (print)",
                     "450 (publication)", "600 (poster)"]
        dpi_choice, ok2 = QInputDialog.getItem(
            self, "Resolution", "DPI:", dpi_items, 1, False)
        if not ok2:
            return
        dpi = int(dpi_choice.split()[0])

        default = f"SJTU-TPMSHX_{key}_{dpi}dpi.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Figure", default,
            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf);;All Files (*)")
        if not path:
            return
        try:
            # Build reproducibility metadata embedded in PNG tEXt / PDF
            # keywords. Matplotlib respects this via savefig's `metadata`
            # kwarg.
            import datetime as _dt_ef
            meta = {
                'Title': f"SJTU-TPMSHX {key}",
                'Author': 'alexlu997',
                'Software': f"SJTU-TPMSHX v{__version__}",
                'CreationDate': _dt_ef.datetime.now().isoformat(timespec='seconds'),
                'Source': 'github.com/alexlu997/SJTU-TPMSHX',
            }
            commit = _git_commit_hash()
            if commit:
                meta['Keywords'] = f"commit={commit}"
            preset = getattr(self, '_active_preset_name', None)
            if preset:
                meta['Subject'] = f"Preset: {preset}"

            ext = path.lower().rsplit('.', 1)[-1] if '.' in path else 'png'
            save_kwargs = dict(dpi=dpi, bbox_inches='tight',
                                facecolor=canvas.fig.get_facecolor())
            if ext in ('png', 'pdf'):
                save_kwargs['metadata'] = meta
            canvas.fig.savefig(path, **save_kwargs)
            self.statusBar().showMessage(
                f"Exported {dpi} DPI → {path}", 6000)
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))
