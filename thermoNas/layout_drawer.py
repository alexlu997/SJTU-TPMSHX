"""Layout drawing helpers for ThermoNAS GUI.

Extracted from main.py (Task B.4). All functions take `window` (a Main_Menu
instance) as first argument. `self.` in original bodies -> `window.`.
"""
import numpy as np
from PySide6.QtWidgets import QMessageBox
from theme import _THEMES


def draw_layout(window):
    """Ex-Main_Menu._draw_layout(self)."""
    try:
        L = float(window.le_L.text()); H = float(window.le_H.text())
    except ValueError:
        QMessageBox.warning(window, "Input Error",
                            "Fill Domain fields first."); return

    window.canvas_layout.fig.clear()
    ax = window.canvas_layout.fig.add_subplot(111)
    window.canvas_layout.axes = [[ax]]
    Lmm, Hmm = L * 1000, H * 1000
    shape_idx = window.combo_shape.currentIndex()

    import main as _main_mod
    _t = _THEMES['light']

    if shape_idx == 0:
        draw_layout_rect(window, ax, L, H, Lmm, Hmm)
    else:
        draw_layout_polygon(window, ax, L, H, Lmm, Hmm)

    ax.set_xlabel('x [mm]', color=_t['ax_text']); ax.set_ylabel('y [mm]', color=_t['ax_text'])
    ax.set_aspect('equal'); ax.set_facecolor(_t['ax_bg'])
    ax.tick_params(colors=_t['ax_text'])
    for sp in ax.spines.values(): sp.set_edgecolor(_t['ax_spine'])
    window.canvas_layout.fig.set_facecolor(_t['fig_bg'])
    window.canvas_layout.draw()
    # Mark as drawn so _switch_tab shows it
    if not hasattr(window, '_drawn_tabs'):
        window._drawn_tabs = set()
    window._drawn_tabs.add('layout')
    window._switch_tab('layout')


def draw_layout_rect(window, ax, L, H, Lmm, Hmm):
    """Ex-Main_Menu._draw_layout_rect(self, ax, L, H, Lmm, Hmm)."""
    import main as _main_mod
    _t = _THEMES['light']
    from matplotlib.patches import Rectangle
    try:
        cfgA = window._fluid_config('A')
        cfgB = window._fluid_config('B')
    except ValueError:
        cfgA = dict(dir=0, in_ctr=H/2, in_w=H, out_ctr=H/2, out_w=H)
        cfgB = dict(dir=3, in_ctr=L/2, in_w=L, out_ctr=L/2, out_w=L)

    ax.add_patch(Rectangle((0, 0), Lmm, Hmm, fill=False, ec=_t['ax_text'], lw=2))

    def _draw_pipe(cfg, label, color, is_inlet):
        d = cfg['dir']
        ctr = (cfg['in_ctr'] if is_inlet else cfg['out_ctr']) * 1000
        w   = (cfg['in_w']   if is_inlet else cfg['out_w'])   * 1000
        lo = ctr - w/2
        wall = window._inlet_wall(d) if is_inlet else window._outlet_wall(d)
        tag = f"{label} {'in' if is_inlet else 'out'}"
        if wall == 'left':
            ax.add_patch(Rectangle((-1.5, lo), 1.2, w, fc=color, ec='none', alpha=0.85))
            ax.annotate(tag, xy=(-3, ctr), fontsize=7, color=color,
                        ha='right', va='center', fontweight='bold')
        elif wall == 'right':
            ax.add_patch(Rectangle((Lmm+0.3, lo), 1.2, w, fc=color, ec='none', alpha=0.85))
            ax.annotate(tag, xy=(Lmm+3, ctr), fontsize=7, color=color,
                        ha='left', va='center', fontweight='bold')
        elif wall == 'bottom':
            ax.add_patch(Rectangle((lo, -1.5), w, 1.2, fc=color, ec='none', alpha=0.85))
            ax.annotate(tag, xy=(ctr, -3.5), fontsize=7, color=color,
                        ha='center', va='top', fontweight='bold')
        else:
            ax.add_patch(Rectangle((lo, Hmm+0.3), w, 1.2, fc=color, ec='none', alpha=0.85))
            ax.annotate(tag, xy=(ctr, Hmm+3.5), fontsize=7, color=color,
                        ha='center', va='bottom', fontweight='bold')

    _draw_pipe(cfgA, 'A', '#ff4422', True)
    _draw_pipe(cfgA, 'A', '#ff4422', False)
    _draw_pipe(cfgB, 'B', '#2266ff', True)
    _draw_pipe(cfgB, 'B', '#2266ff', False)

    # Flow arrows
    cx, cy = Lmm / 2, Hmm / 2
    def _arrow(d, color):
        dx = Lmm * 0.2; dy = Hmm * 0.2
        arrows = {0: (cx-dx, cy, cx+dx, cy), 1: (cx+dx, cy, cx-dx, cy),
                  2: (cx, cy-dy, cx, cy+dy), 3: (cx, cy+dy, cx, cy-dy)}
        x0, y0, x1, y1 = arrows[d]
        ax.annotate('', xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle='->', color=color, lw=1.5))
    _arrow(cfgA['dir'], '#ff6644')
    _arrow(cfgB['dir'], '#4488ff')

    # Zone boundaries and labels
    if window.chk_zones.isChecked():
        z_ax = window._zone_axis()
        from matplotlib.patches import Rectangle as Rect
        ncols = window.zone_table.columnCount()

        if z_ax == 'grid':
            # Grid mode: 6 columns [y0%,y1%,x0%,x1%,L,t]
            for r in range(window.zone_table.rowCount()):
                items = [window.zone_table.item(r, c) for c in range(ncols)]
                if any(it is None or not it.text().strip() for it in items):
                    continue
                yf0 = float(items[0].text())/100; yf1 = float(items[1].text())/100
                xf0 = float(items[2].text())/100; xf1 = float(items[3].text())/100
                x0 = xf0*Lmm; x1 = xf1*Lmm; y0 = yf0*Hmm; y1 = yf1*Hmm
                alpha = 0.08 if r % 2 == 0 else 0.15
                ax.add_patch(Rect((x0,y0), x1-x0, y1-y0,
                                  fc=_t['zone_fill'], ec=_t['zone_fill'], alpha=alpha, lw=0.5))
                L_z, t_z = items[4].text(), items[5].text()
                # Label inside each cell, small font
                ax.text((x0+x1)/2, (y0+y1)/2, f'{L_z}/{t_z}',
                        color=_t['zone_fill'], fontsize=5, ha='center', va='center', alpha=0.8)
        else:
            # 1D mode: 4 columns [start%,end%,L,t]
            for r in range(window.zone_table.rowCount()):
                items = [window.zone_table.item(r, c) for c in range(4)]
                if any(it is None or not it.text().strip() for it in items):
                    continue
                f0 = float(items[0].text())/100; f1 = float(items[1].text())/100
                L_z, t_z = items[2].text(), items[3].text()
                alpha = 0.08 if r % 2 == 0 else 0.15

                if z_ax == 'y':
                    p0 = f0*Hmm; p1 = f1*Hmm
                    ax.add_patch(Rect((0,p0), Lmm, p1-p0,
                                      fc=_t['zone_fill'], ec='none', alpha=alpha))
                    # Label inside zone, right-aligned, avoid pipe labels
                    ax.text(Lmm*0.95, (p0+p1)/2, f'L={L_z} t={t_z}',
                            color=_t['zone_fill'], fontsize=6, va='center', ha='right', alpha=0.9)
                    if f0 > 0.001:
                        ax.axhline(y=p0, color=_t['zone_fill'], ls='--', lw=0.8, alpha=0.6)
                else:
                    p0 = f0*Lmm; p1 = f1*Lmm
                    ax.add_patch(Rect((p0,0), p1-p0, Hmm,
                                      fc=_t['zone_fill'], ec='none', alpha=alpha))
                    ax.text((p0+p1)/2, Hmm*0.05, f'L={L_z}\nt={t_z}',
                            color=_t['zone_fill'], fontsize=5, va='bottom', ha='center', alpha=0.9)
                    if f0 > 0.001:
                        ax.axvline(x=p0, color=_t['zone_fill'], ls='--', lw=0.8, alpha=0.6)

    ax.text(cx, cy, 'TPMS\nDomain', color=_t['ax_text'], ha='center', va='center',
            fontsize=10, fontweight='bold', alpha=0.3)
    ax.set_xlim(-8, Lmm + 8); ax.set_ylim(-8, Hmm + 8)
    dA = window._DIR_MAP[cfgA['dir']]; dB = window._DIR_MAP[cfgB['dir']]
    ax.set_title(f'Geometry: {Lmm:.0f}x{Hmm:.0f}mm | A:{dA} B:{dB}',
                 color=_t['ax_text'], fontsize=10)


def draw_layout_polygon(window, ax, L, H, Lmm, Hmm):
    """Ex-Main_Menu._draw_layout_polygon(self, ax, L, H, Lmm, Hmm)."""
    import main as _main_mod
    _t = _THEMES['light']
    import unstructured_mesh as um
    from matplotlib.patches import Polygon as MplPolygon

    shape = window.combo_shape.currentText()
    verts = um.hexagon(L, H) if shape == 'Hexagon' else um.octagon(L, H)
    verts_mm = verts * 1000
    n_v = len(verts_mm)

    # Draw filled polygon
    ax.add_patch(MplPolygon(verts_mm, closed=True,
                            fc=_t['poly_fill'], ec=_t['ax_text'], lw=2, alpha=0.9))

    # Pipe edge indices
    edge_inA  = window.combo_edge_inA.currentIndex()
    edge_outA = window.combo_edge_outA.currentIndex()
    edge_inB  = window.combo_edge_inB.currentIndex()
    edge_outB = window.combo_edge_outB.currentIndex()

    pipe_edges = {edge_inA: ('A in', '#ff4422'),
                  edge_outA: ('A out', '#ff6644'),
                  edge_inB: ('B in', '#2266ff'),
                  edge_outB: ('B out', '#4488ff')}

    for ei in range(n_v):
        p0 = verts_mm[ei]
        p1 = verts_mm[(ei + 1) % n_v]
        mid = 0.5 * (p0 + p1)

        # Edge direction for outward offset
        edge = p1 - p0
        elen = np.linalg.norm(edge)
        if elen < 1e-6:
            continue
        outward = np.array([edge[1], -edge[0]]) / elen  # outward normal

        if ei in pipe_edges:
            tag, color = pipe_edges[ei]
            # Highlight pipe edge with thick colored line
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=color, lw=5, alpha=0.85,
                    solid_capstyle='round')
            # Label outside
            lbl_pos = mid + outward * 4
            ax.text(lbl_pos[0], lbl_pos[1], tag, color=color, fontsize=8,
                    fontweight='bold', ha='center', va='center')

            # Flow arrow for inlets
            if 'in' in tag:
                arr_start = mid + outward * 3
                arr_end = mid - outward * 2
                ax.annotate('', xy=(arr_end[0], arr_end[1]),
                            xytext=(arr_start[0], arr_start[1]),
                            arrowprops=dict(arrowstyle='->', color=color, lw=1.5))
        else:
            # Edge number label (small, grey)
            lbl_pos = mid + outward * 2.5
            ax.text(lbl_pos[0], lbl_pos[1], f'E{ei}', color='grey', fontsize=6,
                    ha='center', va='center', alpha=0.6)

    # Centre label
    cx = verts_mm[:, 0].mean()
    cy = verts_mm[:, 1].mean()
    ax.text(cx, cy, f'TPMS\n{shape}', color=_t['ax_text'], ha='center', va='center',
            fontsize=10, fontweight='bold', alpha=0.5)

    margin = max(Lmm, Hmm) * 0.1
    ax.set_xlim(verts_mm[:, 0].min() - margin, verts_mm[:, 0].max() + margin)
    ax.set_ylim(verts_mm[:, 1].min() - margin, verts_mm[:, 1].max() + margin)
    ax.set_title(f'Geometry: {shape} {Lmm:.0f}x{Hmm:.0f}mm',
                 color=_t['ax_text'], fontsize=10)
