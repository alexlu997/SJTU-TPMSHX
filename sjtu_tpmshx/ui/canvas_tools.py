"""Canvas interactivity: crosshair overlay, Alt+click annotation pins,
Shift+drag line probe with 1D profile popup.

All three share a single motion + press handler per canvas to minimise
callback overhead on matplotlib's 10-20 Hz event rate.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QLabel

from .theme import get_theme


def install_canvas_tools(window):
    """Wire crosshair / pin / probe handlers to the 2D contour canvases.

    The coord inspector's hover handler is kept untouched — this module
    overlays three additional visual affordances on top of that.
    """
    # 2026-05-20 UI sweep (Tier 20): retain a strong reference to every
    # binding on the window. Matplotlib's CallbackRegistry holds bound
    # methods via WeakMethod, so without an external strong ref the
    # `_CanvasToolsBinding` instance becomes GC-eligible the moment
    # this function returns — crosshair / Alt-pin / Shift-probe then
    # stop firing silently. Also gives `closeEvent` a hook for calling
    # `disconnect()` on each binding during teardown.
    bag = getattr(window, '_canvas_tool_bindings', None)
    if bag is None:
        bag = []
        window._canvas_tool_bindings = bag
    for key in ('canvas_temp', 'canvas_pres', 'canvas_vel'):
        canvas = getattr(window, key, None)
        if canvas is None:
            continue
        bag.append(_CanvasToolsBinding(window, canvas, key))


class _CanvasToolsBinding:
    def __init__(self, window, canvas, key):
        self._w = window
        self._c = canvas
        self._k = key
        self._crosshair_artists = {}      # ax → (vline, hline)
        self._pin_artists = []            # list of (ax, scatter, text)
        self._probe_state = None          # None or ('armed'|'dragging', x0,y0)
        self._probe_line_art = None
        # 2026-05-20 UI sweep: store the connection ids so we can detach
        # cleanly when the canvas is swapped (theme rebuild) or the
        # window closes. Previously the bindings were attached and never
        # detached — old handlers fired into orphaned `self._c` refs.
        self._cids = [
            canvas.mpl_connect('motion_notify_event', self._on_motion),
            canvas.mpl_connect('button_press_event', self._on_press),
            canvas.mpl_connect('button_release_event', self._on_release),
            canvas.mpl_connect('axes_leave_event', self._on_leave),
        ]
        # 2026-05-20 UI sweep (Tier 19): throttle crosshair re-draws to
        # ~30 Hz. The unguarded `draw_idle()` at the end of `_on_motion`
        # was being called on every Qt motion event — at 144 Hz mouse
        # polling that meant up to ~144 paint schedules per second per
        # canvas, which interacted badly with the coord-inspector hover
        # path that ALSO runs off motion_notify_event. draw_idle()
        # coalesces internally, but the Python-side per-event work
        # (axline set_xdata/set_ydata + visibility flips + the
        # probe-drag logic) was still hot on the GUI thread.
        self._last_motion_t = 0.0

    def disconnect(self):
        """Detach all matplotlib callbacks. Idempotent."""
        for cid in self._cids:
            try:
                self._c.mpl_disconnect(cid)
            except Exception:
                pass
        self._cids = []

    # ── Helpers ────────────────────────────────────────────────────
    def _ensure_crosshair(self, ax):
        if ax in self._crosshair_artists:
            return self._crosshair_artists[ax]
        t = get_theme()
        col = t.get('sub_fg', '#888')
        vline = ax.axvline(0, color=col, lw=0.6, ls='--', alpha=0.5,
                            visible=False, zorder=8)
        hline = ax.axhline(0, color=col, lw=0.6, ls='--', alpha=0.5,
                            visible=False, zorder=8)
        self._crosshair_artists[ax] = (vline, hline)
        return vline, hline

    def _canvas_hover_data(self):
        return getattr(self._c, '_hover_data', None)

    # ── Event handlers ────────────────────────────────────────────
    def _on_motion(self, ev):
        if ev.inaxes is None or ev.xdata is None:
            return
        # 30 Hz throttle — see __init__ note. Skip if last paint <33 ms
        # ago AND we are not in the middle of a probe drag (drag previews
        # want full responsiveness, so we let those bypass the gate).
        from time import monotonic as _now
        _is_dragging = bool(
            self._probe_state and self._probe_state[0] == 'dragging')
        if not _is_dragging:
            _t = _now()
            if _t - self._last_motion_t < 0.033:
                return
            self._last_motion_t = _t
        vline, hline = self._ensure_crosshair(ev.inaxes)
        vline.set_xdata([ev.xdata, ev.xdata])
        hline.set_ydata([ev.ydata, ev.ydata])
        vline.set_visible(True); hline.set_visible(True)
        # Probe-drag preview
        if _is_dragging:
            x0, y0 = self._probe_state[1], self._probe_state[2]
            if self._probe_line_art is None:
                t = get_theme()
                self._probe_line_art, = ev.inaxes.plot(
                    [x0, ev.xdata], [y0, ev.ydata],
                    color=t.get('accent_primary', '#3B82F6'),
                    lw=1.8, zorder=9)
            else:
                self._probe_line_art.set_data(
                    [x0, ev.xdata], [y0, ev.ydata])
        self._c.draw_idle()

    def _on_leave(self, _ev):
        for (vline, hline) in self._crosshair_artists.values():
            vline.set_visible(False); hline.set_visible(False)
        self._c.draw_idle()

    def _on_press(self, ev):
        if ev.inaxes is None or ev.xdata is None:
            return
        mods = getattr(ev, 'guiEvent', None)
        alt = False; shift = False
        if mods is not None:
            try:
                m = mods.modifiers()
                alt   = bool(m & Qt.KeyboardModifier.AltModifier)
                shift = bool(m & Qt.KeyboardModifier.ShiftModifier)
            except Exception:
                pass
        if alt:
            self._place_pin(ev)
            return
        if shift:
            self._probe_state = ('dragging', ev.xdata, ev.ydata, ev.inaxes)
            return

    def _on_release(self, ev):
        if self._probe_state is None:
            return
        # Consume probe
        st = self._probe_state
        self._probe_state = None
        if st[0] != 'dragging' or ev.xdata is None or ev.inaxes is not st[3]:
            if self._probe_line_art is not None:
                try: self._probe_line_art.remove()
                except Exception: pass
                self._probe_line_art = None
                self._c.draw_idle()
            return
        x0, y0 = st[1], st[2]; x1, y1 = ev.xdata, ev.ydata
        self._draw_profile(st[3], x0, y0, x1, y1)
        # Leave the probe line visible as a reference.
        self._probe_line_art = None

    # ── Pin / probe actions ───────────────────────────────────────
    def _place_pin(self, ev):
        txt, ok = QInputDialog.getText(
            self._c, "Annotation pin",
            f"Label at ({ev.xdata:.1f}, {ev.ydata:.1f}) mm:")
        if not ok or not txt.strip():
            return
        t = get_theme()
        col = t.get('accent_primary', '#3B82F6')
        sc = ev.inaxes.scatter([ev.xdata], [ev.ydata], s=80, marker='*',
                                 c=col, edgecolors='white', linewidths=1.2,
                                 zorder=11)
        ann = ev.inaxes.annotate(
            txt, xy=(ev.xdata, ev.ydata),
            xytext=(10, 10), textcoords='offset points',
            fontsize=8, color=col,
            bbox=dict(boxstyle='round,pad=0.3',
                      fc=t.get('card_bg', '#fff'), ec=col, lw=0.8))
        self._pin_artists.append((ev.inaxes, sc, ann))
        self._c.draw_idle()
        self._w.statusBar().showMessage(
            f"Pin placed at ({ev.xdata:.1f}, {ev.ydata:.1f}) mm.", 4000)

    def _draw_profile(self, ax, x0, y0, x1, y1):
        """Sample the current `_hover_data` field along the segment
        (x0,y0)-(x1,y1) and pop a 1-D profile dialog."""
        hd = self._canvas_hover_data()
        if not hd:
            return
        fields = hd.get('fields') or []
        names = hd.get('names') or []
        unit = hd.get('unit', '')
        if not fields:
            return
        # Pick the field belonging to the axes the drag started on.
        try:
            axes_flat = [a for row in self._c.axes for a in row]
            field_idx = axes_flat.index(ax)
        except Exception:
            field_idx = 0
        if field_idx >= len(fields):
            return
        field = fields[field_idx]
        name = names[field_idx] if field_idx < len(names) else 'value'

        L = hd.get('L', 1.0); H = hd.get('H', 1.0)
        Nx = hd.get('Nx'); Ny = hd.get('Ny')
        if not (Nx and Ny):
            return
        n_samples = 200
        xs = np.linspace(x0, x1, n_samples) / 1000.0
        ys = np.linspace(y0, y1, n_samples) / 1000.0
        i = np.clip((xs / L * Nx).astype(int), 0, Nx - 1)
        j = np.clip((ys / H * Ny).astype(int), 0, Ny - 1)
        vals = np.asarray(field)[i, j]
        ds = np.hypot(xs - xs[0], ys - ys[0]) * 1000.0  # mm

        self._show_profile_dialog(name, unit, ds, vals, (x0, y0, x1, y1))

    def _show_profile_dialog(self, name, unit, ds, vals, endpoints):
        from .matplotlib_canvas import MatplotlibCanvas
        t = get_theme()
        dlg = QDialog(self._w)
        # 2026-05-20 UI sweep (Tier 19): the prior `dlg.exec()` made
        # this a MODAL dialog, freezing the main window until the user
        # closed the probe popup. Probing several locations in
        # succession or interacting with another tab while a probe
        # was open were both blocked. Switch to a non-modal show()
        # with WA_DeleteOnClose so the figure is cleaned up on close,
        # and retain a reference on the window so the dialog is not
        # garbage-collected before the user dismisses it.
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.setWindowTitle(f"Line probe — {name}")
        dlg.resize(720, 460)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(12, 10, 12, 10); v.setSpacing(8)
        cap = QLabel(
            f"Sample along line from ({endpoints[0]:.1f}, {endpoints[1]:.1f}) "
            f"to ({endpoints[2]:.1f}, {endpoints[3]:.1f}) mm")
        cap.setStyleSheet(
            f"color:{t.get('sub_fg', t['fg'])}; font-size:9pt;"
            "background:transparent; border:none;")
        v.addWidget(cap)
        c = MatplotlibCanvas(1, 1, figsize=(8, 4))
        v.addWidget(c, 1)
        c.fig.patch.set_facecolor(t['fig_bg'])
        ax = c.fig.add_subplot(111)
        ax.set_facecolor(t['ax_bg'])
        ax.plot(ds, vals,
                color=t.get('accent_primary', '#3B82F6'), lw=1.8)
        ax.set_xlabel("Distance along probe [mm]", fontsize=10,
                      color=t['ax_text'])
        ax.set_ylabel(f"{name}  [{unit}]", fontsize=10, color=t['ax_text'])
        ax.tick_params(colors=t['ax_text'], labelsize=9)
        for sp in ax.spines.values():
            sp.set_edgecolor(t['ax_spine'])
        ax.grid(True, alpha=0.2, linewidth=0.5)
        c.fig.subplots_adjust(left=0.12, right=0.96, top=0.94, bottom=0.14)
        c.draw()
        # Retain a strong reference on the window so the non-modal
        # dialog (and its embedded MatplotlibCanvas) is not GC'd before
        # the user closes it. WA_DeleteOnClose set above frees the
        # widget on close.
        _bag = getattr(self._w, '_probe_dialogs', None)
        if _bag is None:
            _bag = []
            self._w._probe_dialogs = _bag
        _bag.append(dlg)
        # Drop the ref from the list once the dialog is destroyed so
        # the list does not grow unbounded across many probes.
        try:
            dlg.destroyed.connect(lambda _o=None, _b=_bag, _d=dlg:
                                   _b.remove(_d) if _d in _b else None)
        except Exception:
            pass
        dlg.show()
        dlg.raise_()
