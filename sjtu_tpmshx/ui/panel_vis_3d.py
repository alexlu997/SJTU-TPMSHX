"""panel_vis_3d.py — embedded PyVistaQt 3D visualisation panel.

Provides `ThreeDVisPanel(QWidget)` — a self-contained Qt widget that hosts a
`pyvistaqt.QtInteractor`. The panel now shows the **full volume** (ray-cast
volume rendering) by default and lets the user manually add a slice plane by
specifying plane orientation + coordinate (in mm). Each slice spawns a 2D
matplotlib pop-up with the corresponding contour plot.

Fields displayed (all None-safe; combo is filtered to what `set_fields`
actually provides):
    Ta       : fluid A temperature [K]
    Tb       : fluid B temperature [K]           (cross-flow only)
    Ts       : solid temperature [K]
    vmag     : fluid A speed magnitude [m/s]
    vmag_B   : fluid B speed magnitude [m/s]     (cross-flow only)
    P_kPa    : fluid A gauge pressure [kPa]
    P_B_kPa  : fluid B gauge pressure [kPa]      (cross-flow only)
    L_mm     : design zoning L-field [mm]

Data entry points:
    panel.load_shanghai_demo(case=8, Nx=30, Ny=15, Nz=5)
    panel.set_fields(Ta=..., Tb=..., Ts=..., vmag=..., vmag_B=...,
                     P_kPa=..., P_B_kPa=..., L_mm=...,
                     dx=..., dy=..., dz=..., real_dims=(Lx, Ly, Lz))

The caller can hand real 3D SIMPLE+LTNE results in via `set_fields`.
"""

from __future__ import annotations
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QLineEdit, QDialog, QFileDialog, QMessageBox, QFrame, QSlider,
)


from ui.vis3d_constants import FIELD_ORDER, FIELD_META, tone_down_plane_widget

# ── Button / label styles (explicit dark-on-light for WCAG contrast) ──
_CTRL_HEIGHT = 32   # unified control height (px)

_BTN_QSS = """
QPushButton {
    color: #1a1f24;
    background: #ffffff;
    border: 1px solid #aeb4ba;
    border-radius: 6px;
    padding: 4px 14px;
    font-size: 10pt;
    font-weight: 500;
}
QPushButton:hover { background: #eef2f6; border-color: #2c5282; color: #0a0a0a; }
QPushButton:pressed { background: #dbe4ed; border-color: #1e3a5f; }
QPushButton:checked { background: #2c5282; color: white; border-color: #1e3a5f; }
QPushButton:disabled { color: #b4b9c0; background: #f8f9fa; border: 1px dashed #d5d8dc; }
"""

# Primary action button — solid accent fill, meant for the one key action in
# the toolbar (Apply). Disabled state keeps a muted outline so it still reads
# as "the primary" when inactive but doesn't scream.
_BTN_PRIMARY_QSS = """
QPushButton {
    color: #ffffff;
    background: #2c5282;
    border: 1px solid #1e3a5f;
    border-radius: 6px;
    padding: 4px 16px;
    font-size: 10pt;
    font-weight: 700;
}
QPushButton:hover { background: #34618f; border-color: #1a3557; }
QPushButton:pressed { background: #1e3a5f; }
QPushButton:disabled { color: #ffffff; background: #94a8c2; border-color: #94a8c2; }
"""

_LABEL_QSS = (
    "QLabel { "
    "color: #1a1f24; font-size: 10pt; font-weight: 500; "
    "background: transparent; border: none; border-radius: 0; "
    "padding: 0 4px 0 0; margin: 0; "
    "}"
)

_STATUS_QSS = (
    "color: #3a3f45; font-size: 9pt; font-weight: 500; "
    "background: #f6f7f9; border-top: 1px solid #e1e4e8; "
    "padding: 6px 12px 6px 12px;"
)

_COMBO_QSS = """
QComboBox {
    color: #1a1f24; background: #ffffff;
    border: 1px solid #aeb4ba; border-radius: 6px;
    padding: 4px 24px 4px 10px;
    font-size: 10pt; font-weight: 500;
    min-width: 140px;
}
QComboBox:hover { border-color: #2c5282; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: top right;
    width: 22px; border-left: 1px solid #aeb4ba;
}
QComboBox QAbstractItemView {
    background: #ffffff; color: #1a1f24;
    selection-background-color: #2c5282; selection-color: white;
    border: 1px solid #aeb4ba; padding: 2px;
}
"""

_LINEEDIT_QSS = """
QLineEdit {
    color: #1a1f24; background: #ffffff;
    border: 1px solid #aeb4ba; border-radius: 6px;
    padding: 4px 8px;
    font-size: 10pt; font-weight: 500;
}
QLineEdit:focus { border-color: #2c5282; }
QLineEdit:disabled { color: #8a9199; background: #f3f4f5; }
QLineEdit[error="true"] { border: 1px solid #c53030; background: #fff5f5; }
QLineEdit[error="true"]:focus { border-color: #c53030; }
"""

# Vertical rule between logical groups in the toolbar
_DIVIDER_QSS = (
    "QFrame { color: #d0d4d9; background: #d0d4d9; "
    "max-width: 1px; min-width: 1px; margin: 6px 4px; }"
)

_SEG_LEFT_QSS = """
QPushButton {
    color: #1a1f24; background: #ffffff; border: 1px solid #aeb4ba;
    border-top-left-radius: 6px; border-bottom-left-radius: 6px;
    border-top-right-radius: 0; border-bottom-right-radius: 0;
    padding: 4px 10px; font-size: 9pt; font-weight: 500;
}
QPushButton:hover { background: #eef2f6; color: #0a0a0a; }
QPushButton:pressed { background: #dbe4ed; border-color: #1e3a5f; }
"""
_SEG_MID_QSS = """
QPushButton {
    color: #1a1f24; background: #ffffff;
    border: 1px solid #aeb4ba; border-left: none;
    border-radius: 0;
    padding: 4px 10px; font-size: 9pt; font-weight: 500;
}
QPushButton:hover { background: #eef2f6; color: #0a0a0a; }
QPushButton:pressed { background: #dbe4ed; border-color: #1e3a5f; }
"""
_SEG_RIGHT_QSS = """
QPushButton {
    color: #1a1f24; background: #ffffff;
    border: 1px solid #aeb4ba; border-left: none;
    border-top-right-radius: 6px; border-bottom-right-radius: 6px;
    border-top-left-radius: 0; border-bottom-left-radius: 0;
    padding: 4px 10px; font-size: 9pt; font-weight: 500;
}
QPushButton:hover { background: #eef2f6; color: #0a0a0a; }
QPushButton:pressed { background: #dbe4ed; border-color: #1e3a5f; }
"""

_SLIDER_QSS = """
QSlider::groove:horizontal {
    border: 1px solid #aeb4ba;
    height: 4px; background: #ffffff;
    margin: 0px; border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #2c5282;
    border: 1px solid #1e3a5f;
    width: 14px; height: 14px;
    margin: -6px 0; border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #34618f; }
QSlider::sub-page:horizontal {
    background: #94a8c2; border-radius: 2px;
}
"""


# Plane-selection: user picks a plane parallel to XY/YZ/XZ; the slicing normal
# is perpendicular to that plane. `coord_axis` names the axis along which the
# user's coordinate value is interpreted.
_PLANE_OPTIONS = [
    ('xy', 'XY (⊥ Z)', 'z'),   # plane parallel to XY → slice at given Z
    ('yz', 'YZ (⊥ X)', 'x'),   # plane parallel to YZ → slice at given X
    ('xz', 'XZ (⊥ Y)', 'y'),   # plane parallel to XZ → slice at given Y
]


class ThreeDVisPanel(QWidget):
    """Embedded 3D visualisation — PyVistaQt interactor + toolbar.

    Default view: volume rendering (ray-casting) of the currently selected
    field. User adds a slice via the Plane/Coord controls; slice is overlaid
    on top of the volume. Each Apply also pops up a 2D matplotlib contour
    window for the chosen slice.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Toolbar (two-row: parameters on top, actions on bottom) ──
        # Single-row layout was overflowing when left-side parameter panel
        # was wide, hiding the view/clear/color/save buttons. Splitting by
        # logical group keeps every control reachable at any window width.
        toolbar_col = QVBoxLayout()
        toolbar_col.setContentsMargins(6, 4, 6, 4)
        toolbar_col.setSpacing(4)

        def _divider():
            d = QFrame()
            d.setFrameShape(QFrame.Shape.VLine)
            d.setStyleSheet(_DIVIDER_QSS)
            d.setFixedHeight(_CTRL_HEIGHT)
            return d

        # ── Row 1: Parameters (Field, Plane, Coord, Opacity) ──
        params = QHBoxLayout(); params.setSpacing(6)
        params.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Field combo
        lbl_f = QLabel("Field:"); lbl_f.setStyleSheet(_LABEL_QSS)
        params.addWidget(lbl_f)
        self.combo_field = QComboBox()
        self.combo_field.setStyleSheet(_COMBO_QSS)
        self.combo_field.setFixedHeight(_CTRL_HEIGHT)
        self.combo_field.currentIndexChanged.connect(self._on_field_changed)
        self.combo_field.setEnabled(False)
        params.addWidget(self.combo_field)

        params.addSpacing(6)

        # Plane combo
        lbl_p = QLabel("Plane:"); lbl_p.setStyleSheet(_LABEL_QSS)
        params.addWidget(lbl_p)
        self.combo_plane = QComboBox()
        for _pid, label, _axis in _PLANE_OPTIONS:
            self.combo_plane.addItem(label, userData=_pid)
        self.combo_plane.setStyleSheet(_COMBO_QSS)
        self.combo_plane.setFixedHeight(_CTRL_HEIGHT)
        self.combo_plane.setMinimumWidth(110)
        self.combo_plane.setEnabled(False)
        self.combo_plane.currentIndexChanged.connect(self._on_plane_changed)
        params.addWidget(self.combo_plane)

        params.addSpacing(6)

        # Coord input (mm) with live range-validation
        self.lbl_coord = QLabel("Coord:")
        self.lbl_coord.setStyleSheet(_LABEL_QSS)
        params.addWidget(self.lbl_coord)
        self.le_coord = QLineEdit("10.0")
        # Range updated dynamically in `_update_coord_label`; placeholder
        # QDoubleValidator accepts any real; we clamp + flag error ourselves.
        self._coord_validator = QDoubleValidator(-1e6, 1e6, 4, self)
        self.le_coord.setValidator(self._coord_validator)
        self.le_coord.setFixedWidth(76)
        self.le_coord.setFixedHeight(_CTRL_HEIGHT)
        self.le_coord.setStyleSheet(_LINEEDIT_QSS)
        self.le_coord.setEnabled(False)
        self.le_coord.setToolTip("Slice coordinate in mm (must be inside domain)")
        self.le_coord.returnPressed.connect(self._on_apply_slice)
        self.le_coord.textChanged.connect(self._on_coord_text_changed)
        params.addWidget(self.le_coord)

        params.addSpacing(10)

        # Opacity slider — controls volume transparency (0 = invisible, 100 = opaque)
        lbl_op = QLabel("Opacity:"); lbl_op.setStyleSheet(_LABEL_QSS)
        params.addWidget(lbl_op)
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(60)          # default 60% — softly cloud-like
        self.slider_opacity.setFixedWidth(110)
        self.slider_opacity.setFixedHeight(_CTRL_HEIGHT)
        self.slider_opacity.setStyleSheet(_SLIDER_QSS)
        self.slider_opacity.setEnabled(False)
        self.slider_opacity.setToolTip(
            "Volume transparency — 0% fully transparent, 100% solid")
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        params.addWidget(self.slider_opacity)
        self.lbl_opacity_val = QLabel("60%")
        self.lbl_opacity_val.setStyleSheet(_LABEL_QSS)
        self.lbl_opacity_val.setFixedWidth(36)
        params.addWidget(self.lbl_opacity_val)
        params.addStretch(1)
        toolbar_col.addLayout(params)

        # ── Row 2: Actions (Apply, Clear, Range, View, Save) ──
        actions = QHBoxLayout(); actions.setSpacing(6)
        actions.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Primary action: Apply
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setStyleSheet(_BTN_PRIMARY_QSS)
        self.btn_apply.setFixedHeight(_CTRL_HEIGHT)
        self.btn_apply.setMinimumWidth(78)
        self.btn_apply.setEnabled(False)
        self.btn_apply.setToolTip(
            "Apply slice + pop up a 2D contour window for archival.\n"
            "(Typing a valid coord already updates the 3D slice in real time;\n"
            " use Apply to capture the current slice as a saveable plot.)")
        self.btn_apply.clicked.connect(self._on_apply_slice)
        actions.addWidget(self.btn_apply)

        actions.addWidget(_divider())

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setStyleSheet(_BTN_QSS)
        self.btn_clear.setFixedHeight(_CTRL_HEIGHT)
        self.btn_clear.setEnabled(False)
        self.btn_clear.setToolTip("Remove the current slice actor from the 3D view.")
        self.btn_clear.clicked.connect(self._on_clear_slice)
        actions.addWidget(self.btn_clear)

        self.btn_clim = QPushButton("Range: Full")
        self.btn_clim.setCheckable(True)
        self.btn_clim.setEnabled(False)
        self.btn_clim.setStyleSheet(_BTN_QSS)
        self.btn_clim.setFixedHeight(_CTRL_HEIGHT)
        self.btn_clim.setToolTip(
            "Color-bar range.\n"
            "  Full  — min/max of the entire 3D domain\n"
            "  Slice — min/max of the current slice only")
        self.btn_clim.clicked.connect(self._on_clim_toggled)
        actions.addWidget(self.btn_clim)

        actions.addWidget(_divider())

        # View preset segmented buttons: Top / Front / Iso
        view_seg = QHBoxLayout(); view_seg.setSpacing(0); view_seg.setContentsMargins(0, 0, 0, 0)
        self.btn_view_top = QPushButton("Top")
        self.btn_view_top.setStyleSheet(_SEG_LEFT_QSS)
        self.btn_view_top.setFixedHeight(_CTRL_HEIGHT); self.btn_view_top.setFixedWidth(46)
        self.btn_view_top.setToolTip("Camera → XY plane looking down -Z")
        self.btn_view_top.setEnabled(False)
        self.btn_view_top.clicked.connect(lambda: self._set_view('top'))
        view_seg.addWidget(self.btn_view_top)

        self.btn_view_front = QPushButton("Front")
        self.btn_view_front.setStyleSheet(_SEG_MID_QSS)
        self.btn_view_front.setFixedHeight(_CTRL_HEIGHT); self.btn_view_front.setFixedWidth(52)
        self.btn_view_front.setToolTip("Camera → XZ plane (looking at -Y face)")
        self.btn_view_front.setEnabled(False)
        self.btn_view_front.clicked.connect(lambda: self._set_view('front'))
        view_seg.addWidget(self.btn_view_front)

        self.btn_view_iso = QPushButton("Iso")
        self.btn_view_iso.setStyleSheet(_SEG_RIGHT_QSS)
        self.btn_view_iso.setFixedHeight(_CTRL_HEIGHT); self.btn_view_iso.setFixedWidth(44)
        self.btn_view_iso.setToolTip("Camera → isometric (default)")
        self.btn_view_iso.setEnabled(False)
        self.btn_view_iso.clicked.connect(lambda: self._set_view('iso'))
        view_seg.addWidget(self.btn_view_iso)
        actions.addLayout(view_seg)

        actions.addWidget(_divider())

        self.btn_shot = QPushButton("Save PNG")
        self.btn_shot.setEnabled(False)
        self.btn_shot.setStyleSheet(_BTN_QSS)
        self.btn_shot.setFixedHeight(_CTRL_HEIGHT)
        self.btn_shot.setToolTip("Screenshot of the 3D viewport.")
        self.btn_shot.clicked.connect(self._on_screenshot)
        actions.addWidget(self.btn_shot)

        actions.addStretch(1)
        toolbar_col.addLayout(actions)
        root.addLayout(toolbar_col)

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
            "No data loaded — set Dimensionality to '3D' in "
            "Domain panel, then click Compute.")
        self.status.setStyleSheet(_STATUS_QSS)
        root.addWidget(self.status)

        # ── State ──
        self._grid: Optional[pv.RectilinearGrid] = None
        self._arrays: dict[str, np.ndarray] = {}     # {key: (Nx,Ny,Nz) array}
        self._dx_mm: Optional[np.ndarray] = None
        self._dy_mm: Optional[np.ndarray] = None
        self._dz_mm: Optional[np.ndarray] = None
        self._L_mm = (0.0, 0.0, 0.0)                 # (Lx, Ly, Lz) domain mm
        self._global_clim: dict = {}
        self._field = None                           # currently selected field key
        self._scale_mode = 'global'
        self._real_dims = None                       # (Lx, Ly, Lz) metres
        self._volume_actor = None
        self._slice_actor_name = 'user_slice'
        self._slice_info = None                      # {'axis': 'x', 'coord_mm': 10.0}
        self._hover_obs_id = None
        self._last_hover_text = ''
        self._base_status_text = ''
        self._popup_dialogs: list = []               # keep refs so they aren't GC'd
        self._opacity = 0.60                         # 0..1, mirrors slider/100
        # Realtime-apply debounce: user typing in coord field keeps firing
        # textChanged; we single-shot a QTimer (240 ms) so the slice rebuilds
        # only after typing pauses, instead of on every keystroke.
        self._coord_debounce = QTimer(self)
        self._coord_debounce.setSingleShot(True)
        self._coord_debounce.setInterval(240)
        self._coord_debounce.timeout.connect(self._on_apply_slice_realtime)

        self._render_placeholder()
        self._setup_hover()

    # ─────────────────────────── public API ───────────────────────────

    def set_fields(self, Ta=None, vmag=None, P_kPa=None, L_mm=None,
                   dx=None, dy=None, dz=None, real_dims=(0.182, 0.042, 0.042),
                   *, Tb=None, Ts=None, vmag_B=None, P_B_kPa=None):
        """Attach 3D fields to the panel. Shape of every field: (Nx, Ny, Nz).

        Positional args preserved for backward compatibility with
        `load_shanghai_demo`; new fields (Tb/Ts/vmag_B/P_B_kPa) are
        keyword-only. Pass `None` for any field that is unavailable
        (e.g. cross-flow fluid B when not solved) — the combo will skip it.

        dx, dy, dz : 1-D grid spacings in metres.
        real_dims  : (Lx, Ly, Lz) metres — used for status + bounds labels.
        """
        if dx is None or dy is None or dz is None:
            raise ValueError("set_fields: dx/dy/dz are required")

        candidate = {
            'Ta': Ta, 'Tb': Tb, 'Ts': Ts,
            'vmag': vmag, 'vmag_B': vmag_B,
            'P_kPa': P_kPa, 'P_B_kPa': P_B_kPa,
            'L_mm': L_mm,
        }
        self._arrays = {k: np.ascontiguousarray(v, dtype=np.float64)
                        for k, v in candidate.items() if v is not None}
        if not self._arrays:
            raise ValueError("set_fields: at least one field must be non-None")

        # 1-D edges / centres in mm
        dx_m = np.asarray(dx, dtype=np.float64)
        dy_m = np.asarray(dy, dtype=np.float64)
        dz_m = np.asarray(dz, dtype=np.float64)
        self._dx_mm = dx_m * 1000.0
        self._dy_mm = dy_m * 1000.0
        self._dz_mm = dz_m * 1000.0
        x_edges = np.concatenate([[0.0], np.cumsum(self._dx_mm)])
        y_edges = np.concatenate([[0.0], np.cumsum(self._dy_mm)])
        z_edges = np.concatenate([[0.0], np.cumsum(self._dz_mm)])
        self._L_mm = (float(x_edges[-1]), float(y_edges[-1]), float(z_edges[-1]))

        grid = pv.RectilinearGrid(x_edges, y_edges, z_edges)
        for key, arr in self._arrays.items():
            grid.cell_data[key] = arr.flatten(order='F')
        self._grid = grid.cell_data_to_point_data()

        self._global_clim = {
            f: (float(self._grid[f].min()), float(self._grid[f].max()))
            for f in self._arrays
        }
        self._real_dims = tuple(real_dims)

        # Populate combo with available fields only (preserves FIELD_ORDER)
        prev_field = self._field
        self.combo_field.blockSignals(True)
        self.combo_field.clear()
        for fkey in FIELD_ORDER:
            if fkey in self._arrays:
                self.combo_field.addItem(FIELD_META[fkey]['label'], userData=fkey)
        self.combo_field.blockSignals(False)

        # Restore previous field selection if still available, else first item
        if prev_field in self._arrays:
            idx = self.combo_field.findData(prev_field)
            if idx >= 0:
                self.combo_field.setCurrentIndex(idx)
            self._field = prev_field
        else:
            self._field = self.combo_field.itemData(0)

        # Enable controls
        for w in (self.combo_field, self.combo_plane, self.le_coord,
                  self.btn_apply, self.btn_clim, self.btn_shot,
                  self.slider_opacity,
                  self.btn_view_top, self.btn_view_front, self.btn_view_iso):
            w.setEnabled(True)
        # btn_clear enabled only once a slice exists
        self.btn_clear.setEnabled(False)
        self._slice_info = None

        self._render_initial_scene()
        self._rebuild_volume()
        self._update_coord_label()
        self._validate_coord_input()
        self._update_status()

    def load_shanghai_demo(self, Nx=30, Ny=15, Nz=5, max_outer=3):
        """Run Shanghai case 8 on coarse grid and push fields in."""
        from ui.demo_vis_3d import run_case_8_fields, build_demo_zoning_field
        self.status.setText("Running Shanghai case 8 … (~15 s)")
        self.repaint()
        sA, Ta, dx, dy, dz, nx, ny, nz, u_A, T_in = run_case_8_fields(
            Nx=Nx, Ny=Ny, Nz=Nz, max_outer=max_outer)

        vA_cc = 0.5 * (sA.v[:, :-1, :] + sA.v[:, 1:, :])
        uc_real = vA_cc.transpose(1, 0, 2).copy()
        uA_cc = 0.5 * (sA.u[:-1, :, :] + sA.u[1:, :, :])
        vc_real = uA_cc.transpose(1, 0, 2).copy()
        wA_cc = 0.5 * (sA.w[:, :, :-1] + sA.w[:, :, 1:])
        wc_real = wA_cc.transpose(1, 0, 2).copy()
        vmag = np.sqrt(uc_real**2 + vc_real**2 + wc_real**2)
        P_kPa = sA.P.transpose(1, 0, 2).copy() / 1000.0

        L_mm = build_demo_zoning_field(nx, ny, nz, dx, dy, dz)

        from ui.demo_vis_3d import L_DOM, H_DOM, LZ
        self.set_fields(Ta=Ta, vmag=vmag, P_kPa=P_kPa, L_mm=L_mm,
                        dx=dx, dy=dy, dz=dz,
                        real_dims=(L_DOM, H_DOM, LZ))

    def cleanup(self):
        """Release GL context + close outstanding matplotlib popups."""
        for dlg in list(self._popup_dialogs):
            try:
                dlg.close()
            except Exception:
                pass
        self._popup_dialogs.clear()
        try:
            self.plotter.close()
        except Exception:
            pass

    # ─────────────────────────── hover probe ──────────────────────────

    def _setup_hover(self):
        try:
            iren = self.plotter.iren.interactor
        except Exception:
            return
        try:
            self._hover_obs_id = iren.AddObserver(
                'MouseMoveEvent', self._on_mouse_move, 1.0)
        except Exception:
            self._hover_obs_id = None

    def _on_mouse_move(self, obj, event):
        """Probe scalar values at cursor position on the slice (if present)."""
        if self._grid is None:
            return
        try:
            import vtk
            x, y = obj.GetEventPosition()
            picker = vtk.vtkPropPicker()
            picker.Pick(x, y, 0, self.plotter.renderer)
            if picker.GetActor() is None:
                if self._last_hover_text and self._base_status_text:
                    self.status.setText(self._base_status_text)
                    self._last_hover_text = ''
                return
            wpos = picker.GetPickPosition()
            idx = self._grid.find_closest_point(wpos)
            if idx < 0:
                return
            parts = [f"Cursor: ({wpos[0]:.1f}, {wpos[1]:.1f}, {wpos[2]:.1f}) mm"]
            for fkey in ('Ta', 'Tb', 'Ts', 'vmag', 'vmag_B',
                         'P_kPa', 'P_B_kPa'):
                if fkey in self._arrays:
                    try:
                        val = float(self._grid[fkey][idx])
                    except Exception:
                        continue
                    parts.append(f"{FIELD_META[fkey]['title']} = "
                                 f"{val:{FIELD_META[fkey]['fmt'][1:]}}")
        except Exception:
            return
        hover_text = "   •   ".join(parts)
        if hover_text != self._last_hover_text:
            self.status.setText(hover_text)
            self._last_hover_text = hover_text

    # ─────────────────────────── callbacks ────────────────────────────

    def _on_field_changed(self, idx):
        if idx < 0 or self._grid is None:
            return
        self._field = self.combo_field.itemData(idx)
        self._rebuild_volume()
        # If a slice is up, refresh it in the new field too
        if self._slice_info is not None:
            self._add_slice_actor(self._slice_info['axis'],
                                  self._slice_info['coord_mm'])
        self._update_status()

    def _on_plane_changed(self, idx):
        self._update_coord_label()
        self._validate_coord_input()
        # If a slice is already showing, switching plane should auto-reapply
        # (reveals the new orientation immediately, no Apply-click needed).
        if self._slice_info is not None and self.btn_apply.isEnabled():
            self._on_apply_slice_realtime()

    def _on_coord_text_changed(self, _txt: str):
        """Live-validate + debounced realtime slice on valid input."""
        self._validate_coord_input()
        if self.btn_apply.isEnabled():
            self._coord_debounce.start()     # 240 ms debounce

    def _on_apply_slice_realtime(self):
        """Realtime-apply variant: slice in-place without popping the 2D window.

        Explicit Apply button still pops the matplotlib window for archival.
        Keeps the 3D viewport fluid while the user scrubs through coords.
        """
        if self._grid is None or not self.btn_apply.isEnabled():
            return
        try:
            coord_mm = float(self.le_coord.text())
        except ValueError:
            return
        axis = self._current_axis()
        hi = {'x': self._L_mm[0], 'y': self._L_mm[1],
              'z': self._L_mm[2]}[axis]
        if coord_mm < 0.0 or coord_mm > hi:
            return
        self._slice_info = {'axis': axis, 'coord_mm': coord_mm}
        self._add_slice_actor(axis, coord_mm)
        self.btn_clear.setEnabled(True)
        self._update_status()

    def _set_view(self, preset: str):
        """Snap camera to a canonical view."""
        pl = self.plotter
        if preset == 'top':
            pl.view_xy()
        elif preset == 'front':
            pl.view_xz()
        else:
            pl.view_isometric()
        pl.camera.zoom(1.35)
        pl.render()

    def _current_axis(self) -> str:
        plane_id = self.combo_plane.currentData()
        return dict((p, a) for (p, _l, a) in _PLANE_OPTIONS)[plane_id]

    def _validate_coord_input(self):
        """Flag the coord field when value is out of domain, disable Apply."""
        if self._grid is None:
            return
        ok = True
        txt = self.le_coord.text().strip()
        try:
            v = float(txt)
        except ValueError:
            ok = False
        else:
            axis = self._current_axis()
            hi = {'x': self._L_mm[0], 'y': self._L_mm[1],
                  'z': self._L_mm[2]}[axis]
            if v < 0.0 or v > hi:
                ok = False
        self.le_coord.setProperty('error', 'false' if ok else 'true')
        # Re-polish so stylesheet property selector applies
        style = self.le_coord.style()
        style.unpolish(self.le_coord); style.polish(self.le_coord)
        self.btn_apply.setEnabled(ok and self.le_coord.isEnabled())
        if not ok and txt:
            axis = self._current_axis()
            hi = {'x': self._L_mm[0], 'y': self._L_mm[1],
                  'z': self._L_mm[2]}[axis]
            self.status.setText(
                f"Coord {txt!r} out of range — must be 0–{hi:.2f} mm.")

    def _on_opacity_changed(self, val: int):
        self._opacity = float(val) / 100.0
        self.lbl_opacity_val.setText(f"{val}%")
        # In-place update the VTK opacity transfer function — rebuilding the
        # whole volume on every slider tick is wasteful (and flashes the
        # scalar bar). The opacity function spans the actor's clim range
        # [lo, hi] with a 2-point ramp 0 → self._opacity, matching the
        # initial `add_volume(opacity=[0.0, self._opacity])` in _rebuild_volume.
        if self._volume_actor is not None and self._field is not None:
            try:
                from vtk import vtkPiecewiseFunction
                lo, hi = self._clim_for(self._field)
                if abs(hi - lo) < 1e-12:
                    hi = lo + 1.0
                pw = vtkPiecewiseFunction()
                pw.AddPoint(lo, min(0.05, self._opacity))
                pw.AddPoint(hi, self._opacity)
                self._volume_actor.GetProperty().SetScalarOpacity(pw)
                self.plotter.render()
                return
            except Exception:
                pass
        # Fall-through: rebuild if actor lookup or piecewise func fails
        self._rebuild_volume()

    def _on_clim_toggled(self, checked: bool):
        self._scale_mode = 'local' if checked else 'global'
        self.btn_clim.setText(f"Range: {'Slice' if checked else 'Full'}")
        self._rebuild_volume()
        if self._slice_info is not None:
            self._add_slice_actor(self._slice_info['axis'],
                                  self._slice_info['coord_mm'])
        self._update_status()

    def _on_apply_slice(self):
        if self._grid is None:
            return
        try:
            coord_mm = float(self.le_coord.text())
        except ValueError:
            self.status.setText("Invalid coordinate — enter a number in mm.")
            return
        plane_id = self.combo_plane.currentData()
        axis = dict((p, a) for (p, _l, a) in _PLANE_OPTIONS)[plane_id]
        lo, hi = 0.0, {'x': self._L_mm[0], 'y': self._L_mm[1],
                       'z': self._L_mm[2]}[axis]
        if coord_mm < lo or coord_mm > hi:
            self.status.setText(
                f"Coord {coord_mm:.2f} mm outside domain [{lo:.1f}, {hi:.1f}] — clamping.")
            coord_mm = max(lo, min(coord_mm, hi))
            self.le_coord.setText(f"{coord_mm:.2f}")
        self._slice_info = {'axis': axis, 'coord_mm': coord_mm}
        self._add_slice_actor(axis, coord_mm)
        self._show_slice_popup(axis, coord_mm)
        self.btn_clear.setEnabled(True)

    def _on_clear_slice(self):
        pl = self.plotter
        try:
            pl.remove_actor(self._slice_actor_name, render=True)
        except Exception:
            pass
        self._slice_info = None
        self.btn_clear.setEnabled(False)
        self._update_status()

    def _on_screenshot(self):
        dflt = f"volume_{self._field}_{self._scale_mode}.png"
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
            "Set Dimensionality = 3D, configure L/H/Lz + inlet/outlet, then Compute.",
            font_size=8, color='black', position='upper_edge',
        )
        pl.reset_camera()

    def _render_initial_scene(self):
        pl = self.plotter
        pl.clear()
        pl.add_mesh(self._grid.outline(), color='#3c4758', line_width=2)
        # Minimal bounds: only endpoint ticks (2 per axis) + smaller font
        # so numbers don't collide with the bounding-box edges. The full 3-tick
        # grid was overlapping the wireframe on narrow geometries like 42 mm.
        pl.show_bounds(
            grid='back', location='outer',
            xtitle='x (mm)', ytitle='y (mm)', ztitle='z (mm)',
            n_xlabels=2, n_ylabels=2, n_zlabels=2,
            all_edges=False, minor_ticks=False, use_2d=False,
            font_size=9, color='#1a1f24', padding=0.02,
        )
        # Corner XYZ triad (rotates with camera view) — orientation ref
        pl.add_axes(
            interactive=False, line_width=2,
            xlabel='X', ylabel='Y', zlabel='Z',
            color='#1a1f24',
        )
        pl.view_isometric()
        # Auto-fit zoom: 182×42×42 mm aspect is very flat → camera framed
        # too loose at 1.35 default. 1.55 packs the bounding box into ~85%
        # of viewport without clipping edges.
        pl.camera.zoom(1.55)

    def _clim_for(self, fkey: str):
        """Resolve (lo, hi) clim for the given field per current scale mode."""
        if self._scale_mode == 'global' or fkey not in self._arrays:
            return self._global_clim.get(fkey, (0.0, 1.0))
        # local: computed from current slice (if any) else global
        if self._slice_info is None:
            return self._global_clim.get(fkey, (0.0, 1.0))
        axis = self._slice_info['axis']
        idx = self._slice_index(axis, self._slice_info['coord_mm'])
        arr = self._arrays[fkey]
        if axis == 'x':
            slc = arr[idx, :, :]
        elif axis == 'y':
            slc = arr[:, idx, :]
        else:
            slc = arr[:, :, idx]
        lo, hi = float(slc.min()), float(slc.max())
        if hi - lo < 1e-12:
            hi = lo + 1.0
        return lo, hi

    def _rebuild_volume(self):
        """Redraw the volume-rendered cube for the current field."""
        if self._grid is None or self._field is None:
            return
        pl = self.plotter
        # Remove previous volume + scalar bars (but keep slice if any)
        try:
            pl.remove_actor('main_volume', render=False)
        except Exception:
            pass
        # Clear ALL existing scalar bars so we never show two for one field.
        # (PyVista's add_volume + slice without `show_scalar_bar=False`
        # previously spawned a horizontal bar at the bottom of the viewport.)
        try:
            pl.remove_scalar_bar()
        except Exception:
            pass
        for fkey in list(FIELD_META.keys()):
            try:
                pl.remove_scalar_bar(FIELD_META[fkey]['title'])
            except Exception:
                pass
        meta = FIELD_META[self._field]
        clim = self._clim_for(self._field)
        # Opacity ramp: minimum 0.05 (not 0) so the lowest-value voxels still
        # carry faint color instead of becoming fully transparent = white.
        # This keeps the volume colorbar consistent with the 2D matplotlib
        # colorbar where every cmap level is solid.
        op_lo = min(0.05, self._opacity)   # 0% slider → truly invisible
        opacity_list = [op_lo, self._opacity]
        try:
            self._volume_actor = pl.add_volume(
                self._grid, scalars=self._field,
                cmap=meta['cmap'], clim=clim,
                opacity=opacity_list, shade=False,
                name='main_volume',
                show_scalar_bar=False,     # suppress volume's built-in bar
            )
            # Refine ray-cast sampling for smoother colour transitions.
            # Default VTK sample distance = ~1 cell diagonal → visible
            # colour banding. Sub-cell sampling (0.25× min cell) gives
            # trilinear-interpolated smooth gradients matching 2D contourf.
            try:
                vol_mapper = self._volume_actor.GetMapper()
                min_cell = min(float(self._dx_mm.min()),
                               float(self._dy_mm.min()),
                               float(self._dz_mm.min()))
                vol_mapper.SetAutoAdjustSampleDistances(False)
                vol_mapper.SetSampleDistance(max(0.01, min_cell * 0.25))
            except Exception:
                pass
            # Add a separate opaque scalar bar so the colorbar doesn't
            # inherit the volume's opacity ramp (which washes out low values).
            # Build the LUT from PyVista/VTK (not matplotlib — VTK has
            # 'rainbow' but matplotlib does not).
            n_lut = 256
            lo, hi = clim
            try:
                import vtk as _vtk
                _lut = _vtk.vtkLookupTable()
                _lut.SetNumberOfTableValues(n_lut)
                _lut.SetRange(lo, hi)
                _lut.SetHueRange(0.667, 0.0)   # VTK rainbow: blue→red
                _lut.Build()
                # Force alpha=1 on every entry
                for _i in range(n_lut):
                    r, g, b, _a = _lut.GetTableValue(_i)
                    _lut.SetTableValue(_i, r, g, b, 1.0)
                _lut.Build()
                pl.add_scalar_bar(
                    title=meta['title'],
                    n_labels=5, vertical=True,
                    position_x=0.905, position_y=0.12,
                    width=0.045, height=0.76,
                    fmt=meta['fmt'],
                    title_font_size=12, label_font_size=11,
                    color='#1a1f24', font_family='courier',
                    bold=False, italic=False,
                    shadow=False, outline=False,
                )
                # Overwrite the plotter's active scalar bar LUT
                if pl.mapper is not None:
                    pl.mapper.SetLookupTable(_lut)
            except Exception:
                # Fallback: let PyVista default render the bar
                pl.add_scalar_bar(
                    title=meta['title'],
                    n_labels=5, vertical=True,
                    position_x=0.905, position_y=0.12,
                    width=0.045, height=0.76,
                    fmt=meta['fmt'],
                    title_font_size=12, label_font_size=11,
                    color='#1a1f24', font_family='courier',
                )

        except Exception as e:
            # GPU/VTK volume rendering may fail on some driver combos; fall
            # back to an outlined bounding box + user slice (if any).
            self.status.setText(
                f"Volume rendering unavailable ({e!s}); use Apply to see slices.")
        pl.render()

    def _slice_index(self, axis: str, coord_mm: float) -> int:
        """Map mm coord along `axis` to nearest cell-centre index."""
        centres = {
            'x': np.cumsum(self._dx_mm) - self._dx_mm / 2,
            'y': np.cumsum(self._dy_mm) - self._dy_mm / 2,
            'z': np.cumsum(self._dz_mm) - self._dz_mm / 2,
        }[axis]
        return int(np.argmin(np.abs(centres - coord_mm)))

    def _add_slice_actor(self, axis: str, coord_mm: float):
        """Add (or replace) a single user slice actor overlaid on the volume."""
        if self._grid is None:
            return
        pl = self.plotter
        try:
            pl.remove_actor(self._slice_actor_name, render=False)
        except Exception:
            pass
        normal = {'x': (1.0, 0.0, 0.0),
                  'y': (0.0, 1.0, 0.0),
                  'z': (0.0, 0.0, 1.0)}[axis]
        cx, cy, cz = self._grid.center
        origin = {'x': (coord_mm, cy, cz),
                  'y': (cx, coord_mm, cz),
                  'z': (cx, cy, coord_mm)}[axis]
        try:
            slc = self._grid.slice(normal=normal, origin=origin)
        except Exception as e:
            self.status.setText(f"Slice failed: {e}")
            return
        meta = FIELD_META[self._field]
        pl.add_mesh(
            slc, scalars=self._field, cmap=meta['cmap'],
            clim=self._clim_for(self._field), lighting=False,
            show_edges=False, name=self._slice_actor_name,
            show_scalar_bar=False,     # volume owns the single scalar bar
        )
        pl.render()

    def _show_slice_popup(self, axis: str, coord_mm: float):
        """Pop up a matplotlib window with the 2D contour of the slice."""
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

        key = self._field
        field = self._arrays[key]
        idx = self._slice_index(axis, coord_mm)
        if axis == 'x':
            slc2d = field[idx, :, :]
            horiz = np.cumsum(self._dy_mm) - self._dy_mm / 2
            vert  = np.cumsum(self._dz_mm) - self._dz_mm / 2
            h_lbl, v_lbl = 'Y [mm]', 'Z [mm]'
        elif axis == 'y':
            slc2d = field[:, idx, :]
            horiz = np.cumsum(self._dx_mm) - self._dx_mm / 2
            vert  = np.cumsum(self._dz_mm) - self._dz_mm / 2
            h_lbl, v_lbl = 'X [mm]', 'Z [mm]'
        else:
            slc2d = field[:, :, idx]
            horiz = np.cumsum(self._dx_mm) - self._dx_mm / 2
            vert  = np.cumsum(self._dy_mm) - self._dy_mm / 2
            h_lbl, v_lbl = 'X [mm]', 'Y [mm]'

        meta = FIELD_META[key]
        dlg = QDialog(self)
        dlg.setWindowTitle(
            f"Slice {axis.upper()}={coord_mm:.2f} mm  |  {meta['label']}")
        fig = Figure(figsize=(7.2, 5.4), dpi=110)
        canvas = FigureCanvasQTAgg(fig)
        ax = fig.add_subplot(111)
        im = ax.contourf(horiz, vert, slc2d.T, levels=30, cmap=meta['cmap'])
        cbar = fig.colorbar(im, ax=ax)
        cbar.set_label(meta['title'])
        ax.set_xlabel(h_lbl); ax.set_ylabel(v_lbl)
        ax.set_aspect('equal')
        ax.set_title(
            f"{meta['label']} — slice {axis.upper()} = {coord_mm:.2f} mm")
        fig.tight_layout()

        lay = QVBoxLayout(dlg)
        toolbar = NavigationToolbar(canvas, dlg)
        lay.addWidget(toolbar)
        lay.addWidget(canvas, stretch=1)
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Save PNG")
        btn_save.setStyleSheet(_BTN_QSS); btn_save.setFixedHeight(_CTRL_HEIGHT)
        btn_save.clicked.connect(
            lambda: self._save_figure(fig, axis, coord_mm, key))
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(_BTN_QSS); btn_close.setFixedHeight(_CTRL_HEIGHT)
        btn_close.clicked.connect(dlg.close)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)
        dlg.resize(900, 680)

        def _on_closed():
            try:
                self._popup_dialogs.remove(dlg)
            except ValueError:
                pass
        dlg.finished.connect(lambda _=None: _on_closed())
        self._popup_dialogs.append(dlg)
        dlg.show()

    def _save_figure(self, fig, axis: str, coord_mm: float, key: str):
        dflt = f"slice_{key}_{axis}_{coord_mm:.2f}mm.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save 2D slice", dflt,
            "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if not path:
            return
        try:
            fig.savefig(path, dpi=200, bbox_inches='tight')
            self.status.setText(f"Saved slice: {path}")
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))

    # ─────────────────────────── status helpers ───────────────────────

    def _update_coord_label(self):
        """Update the coord label to show valid range for the selected plane."""
        if self._grid is None:
            self.lbl_coord.setText("Coord:")
            return
        plane_id = self.combo_plane.currentData()
        axis = dict((p, a) for (p, _l, a) in _PLANE_OPTIONS)[plane_id]
        hi = {'x': self._L_mm[0], 'y': self._L_mm[1], 'z': self._L_mm[2]}[axis]
        self.lbl_coord.setText(f"{axis.upper()} coord (0–{hi:.1f} mm):")

    def _update_status(self):
        if self._grid is None or self._field is None:
            return
        lo, hi = self._global_clim.get(self._field, (0.0, 1.0))
        Lx, Ly, Lz = self._L_mm
        color_range_label = 'Slice' if self._scale_mode == 'local' else 'Full'
        parts = [
            f"Field: {FIELD_META[self._field]['title']}",
            f"Range: {lo:.2f} – {hi:.2f}",
            f"Color Range: {color_range_label}",
            f"Domain: {Lx:.0f} × {Ly:.0f} × {Lz:.0f} mm",
        ]
        if self._slice_info is not None:
            parts.append(
                f"Slice: {self._slice_info['axis'].upper()}"
                f" = {self._slice_info['coord_mm']:.2f} mm")
        else:
            parts.append("Slice: none (click Apply)")
        text = "   •   ".join(parts)
        self._base_status_text = text
        self.status.setText(text)
        self._last_hover_text = ''
