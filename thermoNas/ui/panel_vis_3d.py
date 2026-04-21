"""panel_vis_3d.py — embedded PyVistaQt 3D visualisation panel.

Provides `ThreeDVisPanel(QWidget)` — a self-contained Qt widget that hosts a
`pyvistaqt.QtInteractor` plus a toolbar for field / normal / clim controls
and a "Load Shanghai Demo" trigger.

Fields displayed:
    Ta     : air temperature [K]              (inferno)
    vmag   : speed magnitude [m/s]            (viridis)
    P_kPa  : gauge pressure [kPa]             (plasma)
    L_mm   : design zoning L-field [mm]       (cividis)

Data entry points:
    panel.load_shanghai_demo(case=8, Nx=30, Ny=15, Nz=5)
    panel.set_fields(Ta, vmag, P_kPa, L_mm, dx, dy, dz, real_dims=(Lx, Ly, Lz))

The caller can hand real 3D SIMPLE+LTNE results in via `set_fields`.
"""

from __future__ import annotations
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QButtonGroup, QFileDialog, QMessageBox, QFrame,
)


from ui.vis3d_constants import FIELD_ORDER, FIELD_META, tone_down_plane_widget

# ── Button / label styles (explicit dark-on-light for WCAG contrast) ──
_BTN_QSS = """
QPushButton {
    color: #1a1f24;
    background: #ffffff;
    border: 1px solid #aeb4ba;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 10pt;
    font-weight: 600;
}
QPushButton:hover {
    background: #eef2f6;
    border-color: #2c5282;
    color: #0a0a0a;
}
QPushButton:pressed {
    background: #dbe4ed;
    border-color: #1e3a5f;
}
QPushButton:checked {
    background: #2c5282;
    color: white;
    border-color: #1e3a5f;
}
QPushButton:disabled {
    color: #8a9199;
    background: #f3f4f5;
    border-color: #d5d8dc;
}
"""

_BTN_PRIMARY_QSS = """
QPushButton {
    color: white;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #3c6aa0, stop:1 #2c5282);
    border: 1px solid #1e3a5f;
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 10pt;
    font-weight: bold;
}
QPushButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                stop:0 #4c7ab0, stop:1 #3c6292);
}
QPushButton:pressed {
    background: #1e3a5f;
}
QPushButton:disabled {
    color: #c8cdd2;
    background: #8c96a2;
    border-color: #6c7280;
}
"""

_LABEL_QSS = (
    "color: #1a1f24; font-size: 10pt; font-weight: 600; "
    "background: transparent; padding: 2px 4px;"
)

_STATUS_QSS = (
    "color: #303840; font-family: 'Consolas', 'Roboto Mono', monospace; "
    "font-size: 9pt; background: #f3f4f5; border-top: 1px solid #d5d8dc; "
    "padding: 4px 10px;"
)

_COMBO_QSS = """
QComboBox {
    color: #1a1f24;
    background: #ffffff;
    border: 1px solid #aeb4ba;
    border-radius: 4px;
    padding: 4px 24px 4px 8px;
    font-size: 10pt;
    font-weight: 600;
    min-width: 130px;
}
QComboBox:hover { border-color: #2c5282; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #aeb4ba;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #1a1f24;
    selection-background-color: #2c5282;
    selection-color: white;
    border: 1px solid #aeb4ba;
    padding: 2px;
}
"""


class ThreeDVisPanel(QWidget):
    """Embedded 3D visualisation — PyVistaQt interactor + toolbar."""

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Toolbar ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        lbl_f = QLabel("Field:")
        lbl_f.setStyleSheet(_LABEL_QSS)
        toolbar.addWidget(lbl_f)
        self.combo_field = QComboBox()
        for f in FIELD_ORDER:
            self.combo_field.addItem(FIELD_META[f]['label'], userData=f)
        self.combo_field.setStyleSheet(_COMBO_QSS)
        self.combo_field.currentIndexChanged.connect(self._on_field_changed)
        self.combo_field.setEnabled(False)
        toolbar.addWidget(self.combo_field)

        toolbar.addSpacing(16)

        lbl_n = QLabel("Normal:")
        lbl_n.setStyleSheet(_LABEL_QSS)
        toolbar.addWidget(lbl_n)
        self._normal_buttons = QButtonGroup(self)
        self._normal_buttons.setExclusive(True)
        for n in ('x', 'y', 'z'):
            b = QPushButton(n)
            b.setCheckable(True)
            b.setFixedWidth(36)
            b.setEnabled(False)
            b.setStyleSheet(_BTN_QSS)
            self._normal_buttons.addButton(b)
            toolbar.addWidget(b)
            b.clicked.connect(lambda _=None, normal=n: self._on_normal_clicked(normal))
        self._normal_buttons.buttons()[0].setChecked(True)

        toolbar.addSpacing(16)

        self.btn_clim = QPushButton("clim: global")
        self.btn_clim.setCheckable(True)
        self.btn_clim.setEnabled(False)
        self.btn_clim.setStyleSheet(_BTN_QSS)
        self.btn_clim.setToolTip("Toggle colour-bar range between full-domain "
                                 "(global) and current-slice (local).")
        self.btn_clim.clicked.connect(self._on_clim_toggled)
        toolbar.addWidget(self.btn_clim)

        self.btn_shot = QPushButton("Save PNG")
        self.btn_shot.setEnabled(False)
        self.btn_shot.setStyleSheet(_BTN_QSS)
        self.btn_shot.clicked.connect(self._on_screenshot)
        toolbar.addWidget(self.btn_shot)

        toolbar.addStretch(1)
        root.addLayout(toolbar)

        # ── Divider ──
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        # ── PyVistaQt interactor ──
        self.plotter = QtInteractor(self)
        root.addWidget(self.plotter.interactor, stretch=1)

        pv.set_plot_theme('document')

        # ── Status ──
        self.status = QLabel(
            "No data loaded — set Dimensionality to '3D (uniform)' in "
            "Domain panel, then click Run Calculation.")
        self.status.setStyleSheet(_STATUS_QSS)
        root.addWidget(self.status)

        # ── State ──
        self._grid: Optional[pv.RectilinearGrid] = None
        self._global_clim: dict = {}
        self._normal = 'x'
        self._field = FIELD_ORDER[0]
        self._scale_mode = 'global'       # 'global' | 'local'
        self._real_dims = None            # (Lx, Ly, Lz) metres
        self._slice_actor = None
        self._widget_on = False

        self._render_placeholder()

    # ─────────────────────────── public API ───────────────────────────

    def set_fields(self, Ta: np.ndarray, vmag: np.ndarray, P_kPa: np.ndarray,
                   L_mm: np.ndarray, dx: np.ndarray, dy: np.ndarray,
                   dz: np.ndarray, real_dims=(0.231, 0.042, 0.02)):
        """Attach 3D fields to the panel. Shape: all (Nx, Ny, Nz).

        dx, dy, dz : 1-D grid spacings in metres (edges derived via cumsum).
        real_dims  : (Lx, Ly, Lz) metres — used for the aspect note only.
        """
        x_edges = np.concatenate([[0.0], np.cumsum(dx)]) * 1000.0   # mm
        y_edges = np.concatenate([[0.0], np.cumsum(dy)]) * 1000.0
        z_edges = np.concatenate([[0.0], np.cumsum(dz)]) * 1000.0

        grid = pv.RectilinearGrid(x_edges, y_edges, z_edges)
        grid.cell_data['Ta']    = Ta.flatten(order='F')
        grid.cell_data['vmag']  = vmag.flatten(order='F')
        grid.cell_data['P_kPa'] = P_kPa.flatten(order='F')
        grid.cell_data['L_mm']  = L_mm.flatten(order='F')
        self._grid = grid.cell_data_to_point_data()

        self._global_clim = {
            f: (float(self._grid[f].min()), float(self._grid[f].max()))
            for f in FIELD_ORDER
        }
        self._real_dims = tuple(real_dims)

        # Enable controls
        for w in (self.combo_field, self.btn_clim, self.btn_shot):
            w.setEnabled(True)
        for b in self._normal_buttons.buttons():
            b.setEnabled(True)

        self._render_initial_scene()
        self._rebuild_slice()
        self._update_status()

    def load_shanghai_demo(self, Nx=30, Ny=15, Nz=5, max_outer=3):
        """Run Shanghai case 8 on coarse grid and push fields in."""
        from ui.demo_vis_3d import run_case_8_fields, build_demo_zoning_field
        self.status.setText("Running Shanghai case 8 … (~15 s)")
        self.repaint()
        sA, Ta, dx, dy, dz, nx, ny, nz, u_A, T_in = run_case_8_fields(
            Nx=Nx, Ny=Ny, Nz=Nz, max_outer=max_outer)

        # Extract velocity magnitude + P (real coords)
        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])    # (Ny, Nx, Nz)
        uc_real = vA_cc.transpose(1, 0, 2).copy()
        uA_cc = 0.5 * (sA.u[:-1, :, :] + sA.u[1:, :, :])
        vc_real = uA_cc.transpose(1, 0, 2).copy()
        wA_cc = 0.5 * (sA.w[:, :, :-1] + sA.w[:, :, 1:])
        wc_real = wA_cc.transpose(1, 0, 2).copy()
        vmag = np.sqrt(uc_real**2 + vc_real**2 + wc_real**2)
        P_kPa = sA.P.transpose(1, 0, 2).copy() / 1000.0

        L_mm = build_demo_zoning_field(nx, ny, nz, dx, dy, dz)

        from ui.demo_vis_3d import L_DOM, H_DOM, LZ
        self.set_fields(Ta, vmag, P_kPa, L_mm, dx, dy, dz,
                         real_dims=(L_DOM, H_DOM, LZ))

    def cleanup(self):
        """Release GL context properly before Qt shutdown."""
        try:
            self.plotter.close()
        except Exception:
            pass

    # ─────────────────────────── callbacks ────────────────────────────

    def _on_field_changed(self, idx):
        self._field = self.combo_field.itemData(idx)
        self._rebuild_slice()
        self._update_status()

    def _on_normal_clicked(self, normal: str):
        self._normal = normal
        self._rebuild_slice()
        self._update_status()

    def _on_clim_toggled(self, checked: bool):
        self._scale_mode = 'local' if checked else 'global'
        self.btn_clim.setText(f"clim: {self._scale_mode}")
        self._rebuild_slice()
        self._update_status()

    def _on_screenshot(self):
        dflt = f"slice_{self._field}_{self._normal}_{self._scale_mode}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save 3D view as PNG", dflt, "PNG images (*.png)")
        if not path:
            return
        self.plotter.screenshot(path)
        self.status.setText(f"Saved: {path}")

    # ─────────────────────────── rendering ────────────────────────────

    def _render_placeholder(self):
        pl = self.plotter
        pl.clear()
        pl.add_text(
            "Set Dimensionality = 3D, configure L/H/Lz + inlet/outlet, then Run Calculation.",
            font_size=8, color='black', position='upper_edge',
        )
        pl.reset_camera()

    def _render_initial_scene(self):
        pl = self.plotter
        pl.clear()
        pl.add_mesh(self._grid.outline(), color='#3c4758', line_width=2)
        pl.show_bounds(
            grid='back', location='outer',
            xtitle='x (mm)', ytitle='y (mm)', ztitle='z (mm)',
            n_xlabels=3, n_ylabels=3, n_zlabels=3,
            all_edges=False, minor_ticks=False, use_2d=False,
            font_size=11,        # match 2D matplotlib axis (~10-11 pt)
            color='#1a1f24',
        )
        pl.add_axes(interactive=False, line_width=2)
        pl.view_isometric()
        pl.camera.zoom(1.1)

    def _rebuild_slice(self):
        if self._grid is None:
            return
        pl = self.plotter
        f = self._field
        meta = FIELD_META[f]

        # Tear down previous slice + widget + scalar bars
        if self._widget_on:
            try:
                pl.clear_plane_widgets()
            except Exception:
                pass
            self._widget_on = False
        if self._slice_actor is not None:
            try:
                pl.remove_actor(self._slice_actor)
            except Exception:
                pass
            self._slice_actor = None
        for fkey in FIELD_ORDER:
            try:
                pl.remove_scalar_bar(FIELD_META[fkey]['title'])
            except Exception:
                pass

        # clim + adaptive scalar-bar format
        sbar_fmt = meta['fmt']
        if self._scale_mode == 'global':
            clim = self._global_clim[f]
        else:
            origin = self._grid.center
            slc = self._grid.slice(normal=self._normal, origin=origin)
            if slc.n_points > 0 and f in slc.array_names and slc[f].size > 0:
                lo, hi = float(slc[f].min()), float(slc[f].max())
                if hi - lo < 1e-12:
                    hi = lo + 1.0
                clim = (lo, hi)
                span = hi - lo
                ref = max(abs(lo), abs(hi), 1e-30)
                if span > 0:
                    n_digits = max(2, int(math.ceil(math.log10(ref / span))) + 2)
                    n_digits = min(n_digits, 7)
                    sbar_fmt = f'%.{n_digits}g'
            else:
                clim = self._global_clim[f]

        actor = pl.add_mesh_slice(
            self._grid, scalars=f, cmap=meta['cmap'],
            normal=self._normal, clim=clim,
            lighting=False,
            widget_color='#606870',
            outline_translation=False,
            tubing=False,
            scalar_bar_args={
                'title': meta['title'],
                'n_labels': 6,
                'vertical': True,
                'position_x': 0.895,          # further right — less intrusive
                'position_y': 0.14,
                'width': 0.05,                # narrower bar
                'height': 0.58,
                'fmt': sbar_fmt,
                'title_font_size': 13,        # match 2D pressure title
                'label_font_size': 11,        # match 2D colorbar tick
                'color': '#1a1f24',
                'font_family': 'courier',     # nearest VTK monospace
                'bold': False,
                'italic': False,
                'shadow': False,
                'outline': True,
            },
            show_edges=False, name='live_slice',
        )
        self._slice_actor = actor
        self._widget_on = True
        tone_down_plane_widget(pl)
        pl.render()

    def _update_status(self):
        if self._grid is None:
            return
        f = self._field
        lo, hi = self._global_clim[f]
        dims = self._real_dims or (0, 0, 0)
        Lx, Ly, Lz = (d * 1000 for d in dims)
        # Monospace-friendly alignment: fixed-width labels, separators
        parts = [
            f"{FIELD_META[f]['title']:<18s}",
            f"range=[{lo:>7.3g}, {hi:>7.3g}]",
            f"slice={self._normal}",
            f"clim={self._scale_mode}",
            f"domain={Lx:.0f} x {Ly:.0f} x {Lz:.0f} mm",
        ]
        self.status.setText("   |   ".join(parts))
