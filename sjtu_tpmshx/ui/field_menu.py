"""Context menu + value-history helpers for left-panel LineEdits.

* D2 — field focus shows "recent values" dropdown (last 5 distinct)
* D3 — right-click on field offers Revert + Copy as expression + Restore-recent
"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QMenu, QApplication


def install_field_menus(window):
    """Wire right-click + focus-pop to every session LineEdit.

    Stores `window._field_history = {attr: deque(maxlen=5)}` so the
    history survives across field focus events.
    """
    window._field_history = {}

    # Map attr → (fluid defaults preset or _apply_shanghai_defaults source).
    # We don't replicate every default here — instead pull from Shanghai
    # preset by temporarily applying it to a fresh dict.
    for attr in window._SESSION_LINE_EDITS:
        le = getattr(window, attr, None)
        if le is None:
            continue
        # Qt QLineEdit has a built-in context menu (cut/copy/paste). We add
        # our custom items via the contextMenuEvent override using property
        # injection (avoids subclassing every LineEdit).
        _attach_context_menu(window, le, attr)
        _attach_history_tracker(window, le, attr)


def _attach_context_menu(window, le, attr):
    orig = le.contextMenuEvent

    def _ctx(event):
        # Pull the stock menu (cut/copy/paste/select-all) and append ours.
        menu = le.createStandardContextMenu()
        menu.addSeparator()

        act_revert = menu.addAction("Revert to Shanghai default")
        act_revert.triggered.connect(
            lambda: _revert_field_to_default(window, le, attr))

        # Copy as expression — pairs value with the stored unit from
        # _FIELD_UNITS so a user pasting into a notebook gets context.
        unit_family = window._FIELD_UNITS.get(attr, ('', ''))
        unit_txt = unit_family[1] if unit_family else ''
        unit_label = f" [{unit_txt}]" if unit_txt else ""
        act_expr = menu.addAction(f"Copy with unit{unit_label}")
        act_expr.triggered.connect(
            lambda: _copy_with_unit(le, unit_txt))

        # Recent-values submenu — only built when there's history.
        hist = list(window._field_history.get(attr, []))
        if hist:
            sub = menu.addMenu("Recent values")
            for v in hist:
                a = sub.addAction(v)
                a.triggered.connect(lambda _c=False, val=v: le.setText(val))

        menu.exec(le.mapToGlobal(event.pos()))
        event.accept()

    le.contextMenuEvent = _ctx


def _attach_history_tracker(window, le, attr):
    """Remember a field's last 5 distinct committed values.

    Tracks on `editingFinished` rather than every keystroke so mid-typing
    noise doesn't pollute the history. The deque is stored on the window
    and survives workspace switches."""
    def _push():
        txt = le.text().strip()
        if not txt:
            return
        hist = window._field_history.setdefault(attr, deque(maxlen=5))
        # Avoid duplicates and preserve most-recent-first order.
        if txt in hist:
            try:
                hist.remove(txt)
            except ValueError:
                pass
        hist.appendleft(txt)
    le.editingFinished.connect(_push)


def _revert_field_to_default(window, le, attr):
    """Look up the Shanghai preset default for this attr and write it back."""
    # `_apply_shanghai_defaults` on the window rewrites every input from a
    # preset dict. We replicate the preset locally to avoid re-applying it
    # globally for a single field click.
    _PRESETS = {
        'le_L': '0.182', 'le_H': '0.042', 'le_Lz': '0.042',
        'le_Lcell': '7.0', 'le_t': '0.6', 'le_ks': '16.0',
        'le_uA': '20.0',  'le_TinA': '422.0', 'le_PinA': '192362',
        'le_uB': '0.133', 'le_TinB': '300.0', 'le_PinB': '101973',
        'le_Nx': '30',    'le_Ny': '20',      'le_Nz': '5',
        'le_T_init_s': '325.0',
        'le_pipeA_in_ctr': '0.021', 'le_pipeA_in_w': '0.042',
        'le_pipeA_out_ctr': '0.021', 'le_pipeA_out_w': '0.042',
        'le_pipeB_in_ctr': '0.154', 'le_pipeB_in_w': '0.042',
        'le_pipeB_out_ctr': '0.028', 'le_pipeB_out_w': '0.042',
    }
    val = _PRESETS.get(attr)
    if val is None:
        window.statusBar().showMessage(
            f"No preset default for {attr}.", 3000)
        return
    # Temperature fields are authored in K; convert if UI shows °C.
    if attr in ('le_TinA', 'le_TinB', 'le_T_init_s') and \
            getattr(window, '_temp_unit', 'K') == 'C':
        try:
            val = f"{float(val) - 273.15:.2f}"
        except Exception:
            pass
    le.setText(val)
    window.statusBar().showMessage(
        f"{attr} reverted to Shanghai default ({val}).", 4000)


def _copy_with_unit(le, unit_txt):
    txt = le.text().strip()
    if not txt:
        return
    clip = QApplication.clipboard()
    clip.setText(f"{txt} {unit_txt}".strip())
