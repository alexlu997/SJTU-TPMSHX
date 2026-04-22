"""Layout drawing helpers for SJTU-TPMSHX GUI.

Extracted from main.py (Task B.4). All functions take `window` (a Main_Menu
instance) as first argument. `self.` in original bodies -> `window.`.
"""
import numpy as np
from PySide6.QtWidgets import QMessageBox
from .theme import _THEMES


def draw_layout(window):
    """Draw geometry. 2D (rect/hex/oct) or 3D cuboid wireframe based on mode."""
    try:
        L = float(window.le_L.text()); H = float(window.le_H.text())
    except ValueError:
        QMessageBox.warning(window, "Input Error",
                            "Fill Domain fields first."); return

    window.canvas_layout.fig.clear()
    Lmm, Hmm = L * 1000, H * 1000
    _t = _THEMES['light']

    # 3D mode → 3D cuboid wireframe + inlet/outlet shading
    is_3d = (hasattr(window, 'combo_dim')
             and window.combo_dim.currentIndex() == 1)
    if is_3d:
        try:
            Lz = float(window.le_Lz.text())
        except ValueError:
            QMessageBox.warning(window, "Input Error",
                                "Fill Lz field first."); return
        ax = window.canvas_layout.fig.add_subplot(111, projection='3d')
        window.canvas_layout.axes = [[ax]]
        draw_layout_rect_3d(window, ax, L, H, Lz)
        ax.set_facecolor(_t['ax_bg'])
    else:
        # Restore canvas_wheel_zoom behaviour if a prior 3D draw overrode it
        _canvas = window.canvas_layout
        if hasattr(_canvas, '_orig_wheel_event'):
            _canvas.wheelEvent = _canvas._orig_wheel_event
        ax = _canvas.fig.add_subplot(111)
        window.canvas_layout.axes = [[ax]]
        shape_idx = window.combo_shape.currentIndex()
        if shape_idx == 0:
            draw_layout_rect(window, ax, L, H, Lmm, Hmm)
        else:
            draw_layout_polygon(window, ax, L, H, Lmm, Hmm)
        ax.set_xlabel('x [mm]', color=_t['ax_text'])
        ax.set_ylabel('y [mm]', color=_t['ax_text'])
        ax.set_aspect('equal')
        ax.set_facecolor(_t['ax_bg'])
        ax.tick_params(colors=_t['ax_text'])
        for sp in ax.spines.values():
            sp.set_edgecolor(_t['ax_spine'])

    window.canvas_layout.fig.set_facecolor(_t['fig_bg'])
    window.canvas_layout.draw()
    if not hasattr(window, '_drawn_tabs'):
        window._drawn_tabs = set()
    window._drawn_tabs.add('layout')
    if hasattr(window, 'btn_export_figure'):
        window.btn_export_figure.setEnabled(True)
    window._switch_tab('layout')


def draw_layout_rect_3d(window, ax, L, H, Lz):
    """Draw 3D cuboid wireframe + inlet/outlet face shading for fluid A + B.

    Engineering convention: external double arrows (inlet: pointing IN,
    outlet: pointing OUT). Inline "Inlet_A/Outlet_A/Inlet_B/Outlet_B"
    labels replace title legend. Small origin triad at (0,0,0).
    """
    import main as _main_mod
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    Lmm, Hmm, Lzmm = L * 1000, H * 1000, Lz * 1000

    # Cuboid edges
    pts = np.array([
        [0, 0, 0], [Lmm, 0, 0], [Lmm, Hmm, 0], [0, Hmm, 0],
        [0, 0, Lzmm], [Lmm, 0, Lzmm], [Lmm, Hmm, Lzmm], [0, Hmm, Lzmm],
    ])
    edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),
             (0,4),(1,5),(2,6),(3,7)]
    for i, j in edges:
        ax.plot(*zip(pts[i], pts[j]), color='#3c4758', lw=1.4)

    def _face_patch(verts, color, alpha):
        poly = Poly3DCollection([verts], alpha=alpha, facecolor=color,
                                 edgecolor='#1a1f24', linewidths=1.2)
        ax.add_collection3d(poly)

    def _rect_face(axis, val, ctr, w, low, high):
        lo = max(ctr - w / 2, low); hi = min(ctr + w / 2, high)
        if axis == 'x':
            return [(val, lo, 0), (val, hi, 0), (val, hi, Lzmm), (val, lo, Lzmm)]
        return [(lo, val, 0), (hi, val, 0), (hi, val, Lzmm), (lo, val, Lzmm)]

    INLET_COL = '#e8751a'
    OUTLET_COL = '#1e5a9e'
    face_alpha = 0.68

    def _draw_fluid(cfg, label_tag, label_offset):
        """Shade inlet (orange) + outlet (blue) faces and place inline labels."""
        d = cfg['dir']
        in_ctr_mm = cfg['in_ctr'] * 1000; in_w_mm = cfg['in_w'] * 1000
        out_ctr_mm = cfg['out_ctr'] * 1000; out_w_mm = cfg['out_w'] * 1000
        if d in (0, 1):
            in_face_val = 0.0 if d == 0 else Lmm
            out_face_val = Lmm if d == 0 else 0.0
            _face_patch(_rect_face('x', in_face_val, in_ctr_mm, in_w_mm, 0, Hmm),
                        INLET_COL, face_alpha)
            _face_patch(_rect_face('x', out_face_val, out_ctr_mm, out_w_mm, 0, Hmm),
                        OUTLET_COL, face_alpha)
            ax.text(in_face_val, in_ctr_mm, Lzmm + label_offset,
                    f'Inlet_{label_tag}', color=INLET_COL, fontsize=9,
                    fontweight='bold', ha='center')
            ax.text(out_face_val, out_ctr_mm, Lzmm + label_offset,
                    f'Outlet_{label_tag}', color=OUTLET_COL, fontsize=9,
                    fontweight='bold', ha='center')
        else:
            in_face_val = 0.0 if d == 2 else Hmm
            out_face_val = Hmm if d == 2 else 0.0
            _face_patch(_rect_face('y', in_face_val, in_ctr_mm, in_w_mm, 0, Lmm),
                        INLET_COL, face_alpha)
            _face_patch(_rect_face('y', out_face_val, out_ctr_mm, out_w_mm, 0, Lmm),
                        OUTLET_COL, face_alpha)
            ax.text(in_ctr_mm, in_face_val, Lzmm + label_offset,
                    f'Inlet_{label_tag}', color=INLET_COL, fontsize=9,
                    fontweight='bold', ha='center')
            ax.text(out_ctr_mm, out_face_val, Lzmm + label_offset,
                    f'Outlet_{label_tag}', color=OUTLET_COL, fontsize=9,
                    fontweight='bold', ha='center')

    try:
        fA = window._fluid_config('A')
    except Exception:
        fA = dict(dir=0, in_ctr=H / 2, in_w=H, out_ctr=H / 2, out_w=H)
    _draw_fluid(fA, 'A', Lzmm * 0.15)

    try:
        fB = window._fluid_config('B')
        _draw_fluid(fB, 'B', Lzmm * 0.30)
    except Exception:
        pass

    # Origin triad
    triad_len = max(Lmm, Hmm, Lzmm) * 0.06
    ax.quiver(0, 0, 0, triad_len, 0, 0, color='#d13b3b', arrow_length_ratio=0.3,
               linewidth=1.8)
    ax.quiver(0, 0, 0, 0, triad_len, 0, color='#3bbd3b', arrow_length_ratio=0.3,
               linewidth=1.8)
    ax.quiver(0, 0, 0, 0, 0, triad_len, color='#3b68d1', arrow_length_ratio=0.3,
               linewidth=1.8)

    # Axis labels — bold
    ax.set_xlabel('x [mm]', color='#1a1f24', fontsize=11,
                  fontweight='bold', labelpad=10)
    ax.set_ylabel('y [mm]', color='#1a1f24', fontsize=11,
                  fontweight='bold', labelpad=10)
    ax.set_zlabel('z [mm]', color='#1a1f24', fontsize=11,
                  fontweight='bold', labelpad=10)

    # Ticks: only endpoints (clean up "115.5" midpoint artefact)
    # For long axes (>= 100 mm) also include a round midpoint.
    def _endpoint_ticks(L_mm):
        if L_mm >= 100:
            mid = round(L_mm / 100) * 50   # nearest 50 mm
            if 0 < mid < L_mm:
                return [0, mid, L_mm]
        return [0, L_mm]
    ax.set_xticks(_endpoint_ticks(Lmm))
    ax.set_yticks(_endpoint_ticks(Hmm))
    ax.set_zticks(_endpoint_ticks(Lzmm))
    ax.tick_params(colors='#1a1f24', labelsize=9)

    # Background panes: soft grey
    try:
        for pane_axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            pane_axis.pane.fill = False
            pane_axis.pane.set_edgecolor('#e0e0e0')
            pane_axis._axinfo['grid'].update({
                'color': '#cfd4d9', 'linestyle': ':', 'linewidth': 0.7,
            })
    except Exception:
        pass

    # Clean title — legend now inline
    ax.set_title('3D Computational Domain   (inlet orange · outlet blue)',
                 color='#1a1f24', fontsize=12, fontweight='bold', pad=14)

    # ── Mouse-wheel camera zoom (override canvas_wheel_zoom which scrolls) ──
    # Save original wheelEvent once so 2D mode can restore it.
    canvas = ax.figure.canvas
    if not hasattr(canvas, '_orig_wheel_event'):
        canvas._orig_wheel_event = canvas.wheelEvent

    def _qt_wheel_zoom_3d(evt):
        delta = evt.angleDelta().y()
        if delta == 0:
            evt.ignore(); return
        factor = 0.88 if delta > 0 else 1.14
        ax.dist = max(2.0, min(30.0, ax.dist * factor))
        canvas.draw_idle()
        evt.accept()

    canvas.wheelEvent = _qt_wheel_zoom_3d

    # Aspect ratio (soft-stretch thin axes for visibility)
    max_dim = max(Lmm, Hmm, Lzmm)
    min_dim = min(Lmm, Hmm, Lzmm)
    if max_dim / min_dim > 3.0:
        try:
            ax.set_box_aspect((
                1.0,
                (Hmm / max_dim) ** 0.5,
                (Lzmm / max_dim) ** 0.5))
        except Exception:
            pass
    else:
        try:
            ax.set_box_aspect((Lmm, Hmm, Lzmm))
        except Exception:
            pass

    ax.view_init(elev=22, azim=-52)
    try:
        ax.figure.subplots_adjust(left=0.02, right=0.98, top=0.92, bottom=0.02)
    except Exception:
        pass


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
    from solvers import unstructured_mesh as um
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
