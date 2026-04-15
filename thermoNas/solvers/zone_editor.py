"""Zone configuration editor helpers.

Extracted from main.py (Task B.5). All functions take `window` (Main_Menu
instance) as first argument. Intra-module calls use top-level function
names, not `window._method(...)`.
"""
from PySide6.QtWidgets import QTableWidgetItem


def zone_mode_changed(window, idx):
    """Ex-Main_Menu._zone_mode_changed(self, idx)."""
    is_grid = (idx == 2)
    window.lbl_nx.setVisible(is_grid)
    window.btn_add_x.setVisible(is_grid)
    window.btn_rm_x.setVisible(is_grid)
    if is_grid:
        zone_rebuild_grid(window)
    elif window.zone_table.columnCount() != 4:
        zone_init_1d(window, 3)


def zone_is_grid(window):
    """Ex-Main_Menu._zone_is_grid(self)."""
    return window.combo_zone_axis.currentIndex() == 2


def zone_init_1d(window, n):
    """Ex-Main_Menu._zone_init_1d(self, n)."""
    window.zone_table.setColumnCount(4)
    window.zone_table.setHorizontalHeaderLabels(["start%", "end%", "L [mm]", "t [mm]"])
    window.zone_table.setRowCount(n)
    step = 100.0 / n
    for r in range(n):
        for c, v in enumerate([f"{r*step:.1f}", f"{(r+1)*step:.1f}", "6.0", "0.3"]):
            window.zone_table.setItem(r, c, QTableWidgetItem(v))
    zone_resize(window)


def zone_add_row(window):
    """Ex-Main_Menu._zone_add_row(self)."""
    if zone_is_grid(window):
        ny = window.zone_table.rowCount() // max(window._grid_nx, 1) + 1
        zone_rebuild_grid(window, ny=ny)
    else:
        r = window.zone_table.rowCount()
        last_end = "100.0"
        if r > 0:
            it = window.zone_table.item(r - 1, 1)
            last_end = it.text() if it else "100.0"
        window.zone_table.insertRow(r)
        for c, v in enumerate([last_end, "100.0", "6.0", "0.3"]):
            window.zone_table.setItem(r, c, QTableWidgetItem(v))
        zone_resize(window)


def zone_remove_row(window):
    """Ex-Main_Menu._zone_remove_row(self)."""
    if zone_is_grid(window):
        ny = window.zone_table.rowCount() // max(window._grid_nx, 1)
        if ny > 1:
            zone_rebuild_grid(window, ny=ny - 1)
    else:
        if window.zone_table.rowCount() > 1:
            window.zone_table.removeRow(window.zone_table.rowCount() - 1)
            zone_resize(window)


def zone_add_col(window):
    """Ex-Main_Menu._zone_add_col(self)."""
    ny = window.zone_table.rowCount() // max(window._grid_nx, 1)
    window._grid_nx += 1
    zone_rebuild_grid(window, ny=ny)


def zone_remove_col(window):
    """Ex-Main_Menu._zone_remove_col(self)."""
    ny = window.zone_table.rowCount() // max(window._grid_nx, 1)
    if window._grid_nx > 1:
        window._grid_nx -= 1
        zone_rebuild_grid(window, ny=ny)


def zone_rebuild_grid(window, ny=None):
    """Ex-Main_Menu._zone_rebuild_grid(self, ny=None)."""
    nx = window._grid_nx
    if ny is None:
        ny = max(window.zone_table.rowCount() // max(nx, 1), 2)
    # Save old L/t
    old_Lt = {}
    for r in range(window.zone_table.rowCount()):
        ncol = window.zone_table.columnCount()
        Li = window.zone_table.item(r, ncol - 2)
        ti = window.zone_table.item(r, ncol - 1)
        if Li and ti:
            old_Lt[r] = (Li.text(), ti.text())

    window.zone_table.setColumnCount(6)
    window.zone_table.setHorizontalHeaderLabels(
        ["y0%", "y1%", "x0%", "x1%", "L [mm]", "t [mm]"])
    n_total = ny * nx
    window.zone_table.setRowCount(n_total)
    sy, sx = 100.0 / ny, 100.0 / nx
    for iy in range(ny):
        for ix in range(nx):
            r = iy * nx + ix
            Lt = old_Lt.get(r, ("6.0", "0.3"))
            vals = [f"{iy*sy:.1f}", f"{(iy+1)*sy:.1f}",
                    f"{ix*sx:.1f}", f"{(ix+1)*sx:.1f}", Lt[0], Lt[1]]
            for c, v in enumerate(vals):
                window.zone_table.setItem(r, c, QTableWidgetItem(v))
    zone_resize(window)


def zone_resize(window):
    """Ex-Main_Menu._zone_resize(self)."""
    window.zone_table.setMinimumHeight(min(400, 34 + 30 * window.zone_table.rowCount()))


def zone_axis(window):
    """Ex-Main_Menu._zone_axis(self). Return 'y', 'x', or 'grid' based on combo selection."""
    idx = window.combo_zone_axis.currentIndex()
    return ['y', 'x', 'grid'][idx]


def build_zone_config(window):
    """Ex-Main_Menu._build_zone_config(self).

    Read zone table and build ZoneConfig (1D) or grid arrays (2D).
    Returns None if zones disabled.
    For 1D: returns ZoneConfig object.
    For grid: returns ZoneConfig (unused) but stores grid info in window._zone_grid.
    """
    if not window.chk_zones.isChecked():
        window._zone_grid = None
        return None
    from .zone_config import ZoneConfig, Zone
    tpms_type = window.combo_tpms.currentText()
    k_s = float(window.le_ks.text())

    if not zone_is_grid(window):
        # 1D mode
        window._zone_grid = None
        zones = []
        for r in range(window.zone_table.rowCount()):
            items = [window.zone_table.item(r, c) for c in range(4)]
            if any(it is None or not it.text().strip() for it in items):
                continue
            y0 = float(items[0].text()) / 100.0
            y1 = float(items[1].text()) / 100.0
            L  = float(items[2].text())
            t  = float(items[3].text())
            zones.append(Zone(f"zone_{r}", y0, y1, L, t))
        if not zones:
            return None
        return ZoneConfig(zones=zones, tpms_type=tpms_type, k_s=k_s)
    else:
        # Grid mode: 6 columns [y0%, y1%, x0%, x1%, L, t]
        grid_cells = []
        for r in range(window.zone_table.rowCount()):
            items = [window.zone_table.item(r, c) for c in range(6)]
            if any(it is None or not it.text().strip() for it in items):
                continue
            y0 = float(items[0].text()) / 100.0
            y1 = float(items[1].text()) / 100.0
            x0 = float(items[2].text()) / 100.0
            x1 = float(items[3].text()) / 100.0
            Lv = float(items[4].text())
            tv = float(items[5].text())
            grid_cells.append({'y0':y0,'y1':y1,'x0':x0,'x1':x1,'L':Lv,'t':tv})
        window._zone_grid = {'cells': grid_cells,
                             'tpms_type': tpms_type, 'k_s': k_s}
        return ZoneConfig(zones=[Zone('grid', 0, 1, 6.0, 0.3)],
                          tpms_type=tpms_type, k_s=k_s)
