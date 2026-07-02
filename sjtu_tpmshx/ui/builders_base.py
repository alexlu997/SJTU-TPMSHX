"""Shared widget-row factories for the page builders.

Split out of ui_builders.py (Batch-2, 2026-06-10): the pure helpers that
every ``build_page_*`` module uses — section/row/res_row/add_row (thin
Phase-5 delegators to FieldFactory), the COMPUTED divider, and the
``_ResultLabel`` value widget with its unit-parsing helper.

All functions keep the legacy ``window`` first argument for call-site
compatibility even where it is unused.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame

from .theme import get_theme


def section(window, parent_lay, title, title_style, frame_style):
    """Ex-Main_Menu._section. Phase 5: delegates to FieldFactory.

    The ``window`` argument is unused — kept for backward compatibility
    with every existing call site in ``build_page_*``. Returns
    ``(grid_layout, container_widget)``.
    """
    from .field_factory import default_factory
    return default_factory().section(parent_lay, title,
                                       title_style, frame_style)


def collapsible_section(window, parent_lay, title, title_style, frame_style,
                        expanded=False, on_toggle=None):
    """Collapsible variant of :func:`section`.

    Same ``(grid, container)`` return and the same visual card, but the
    title becomes a clickable header that shows / hides the body. A chevron
    prefixes the title (``▾`` open · ``▸`` collapsed). Mirrors the top-level
    accordion in ``ui_builders.build_param_tabs`` but scoped to one in-page
    sub-section, so rarely-touched "advanced" controls collapse out of the
    way by default.

    ``on_toggle(is_open)`` — optional callback fired after each *user* click
    (not the initial state). Showing the frame makes Qt blanket-show every
    child, which would re-reveal widgets a per-mode gate (e.g.
    ``_on_dim_changed``) had hidden; pass that gate here so it re-asserts
    per-widget visibility right after an expand. ``window`` is unused — kept
    for call-site symmetry with :func:`section`.
    """
    from .field_factory import default_factory
    grid, container = default_factory().section(parent_lay, title,
                                                 title_style, frame_style)
    clay = container.layout()            # QVBoxLayout: [title, frame]
    title_lbl = clay.itemAt(0).widget()
    frame = clay.itemAt(1).widget()
    base = (title or "").strip()

    def _apply(exp):
        frame.setVisible(exp)
        title_lbl.setText(("▾  " if exp else "▸  ") + base)

    _apply(expanded)

    # Prominent, obviously-clickable header bar (accent text + accent border +
    # raised fill) so the collapsed section is easy to spot — the plain slate
    # section titles otherwise blend in and get scanned past. Overrides the
    # palette pin that FieldFactory.section sets on the title label.
    from PySide6.QtGui import QColor, QPalette
    _ht = get_theme()
    _acc = _ht.get('accent_primary', '#3B82F6')
    _txt = _ht.get('val', _acc)
    title_lbl.setStyleSheet(
        f"QLabel{{color:{_txt}; font-size:11pt; font-weight:700;"
        f" background:{_ht.get('surface_elevated', _ht['card_bg'])};"
        f" border:1px solid {_acc}; border-radius:6px; padding:7px 12px;}}"
        f"QLabel:hover{{background:{_ht.get('chk_hover_bg', _ht['card_bg'])};}}")
    _pal = title_lbl.palette()
    _pal.setColor(QPalette.ColorRole.WindowText, QColor(_txt))
    _pal.setColor(QPalette.ColorRole.Text, QColor(_txt))
    title_lbl.setPalette(_pal)
    title_lbl.setCursor(Qt.CursorShape.PointingHandCursor)

    def _toggle(_ev):
        _apply(not frame.isVisible())
        if on_toggle is not None:
            on_toggle(frame.isVisible())

    title_lbl.mousePressEvent = _toggle
    # Programmatic expand/collapse hook (ui-ia-batch1): lets callers open a
    # collapsed section when its content becomes relevant (e.g. compute_tpms
    # auto-expands "Computed geometry" once values exist).
    container._set_expanded = _apply
    return grid, container


def row(window, g, row_idx, text, default):
    """Ex-Main_Menu._row -> QLineEdit. Phase 5: delegates to FieldFactory.

    Note: parameter `row` renamed to `row_idx` to avoid shadowing the
    function name. ``window`` retained for call-site compatibility.
    """
    from .field_factory import default_factory
    return default_factory().row(g, row_idx, text, default)


def res_row(window, g, row_idx, text, col=0):
    """Label + computed-value row. Phase 5: delegates to FieldFactory."""
    from .field_factory import default_factory
    return default_factory().res_row(g, row_idx, text, col=col)


def add_row(window, g, row_idx, text, widget):
    """Ex-Main_Menu._add_row. Phase 5: delegates to FieldFactory."""
    from .field_factory import default_factory
    return default_factory().add_row(g, row_idx, text, widget)


def _computed_divider(g, row_idx, cols=2):
    """Insert a left-aligned `COMPUTED` caption + thin horizontal rule into
    grid `g` at the given row, spanning `cols` columns.

    Replaces the older `── computed ──` text separator. Visual weight is
    deliberately low — this is a layout hint, not a header.
    """
    t = get_theme()
    sub_fg = t.get('sub_fg', t['fg'])
    card_border = t.get('card_border', '#334155')

    holder = QWidget()
    holder.setStyleSheet("background:transparent;")
    h = QHBoxLayout(holder)
    h.setContentsMargins(0, 6, 0, 2)
    h.setSpacing(8)

    cap = QLabel("COMPUTED")
    cap.setStyleSheet(
        f"color:{sub_fg}; font-size:8pt; font-weight:600; letter-spacing:1.2px;"
        "background:transparent; border:none; padding:0;")
    cap.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    h.addWidget(cap, 0)

    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(
        f"background:{card_border}; border:none; color:{card_border};")
    h.addWidget(line, 1)

    g.addWidget(holder, row_idx, 0, 1, cols)


class _ResultLabel(QLabel):
    """QLabel that flips its dynamic `valState` property between `empty`
    ("—", muted italic) and `filled` (bold accent) as its text changes.

    A single `_VAL` stylesheet hosts both `QLabel[valState="empty"]` and
    `QLabel[valState="filled"]` selectors; Qt repolishes after each property
    change so call-sites that do `label.setText(...)` see the right look
    without touching styles themselves.

    Right-click pops a small menu with "Copy value" / "Copy with units";
    the unit string is parsed once from the row label at creation time.
    """
    _EMPTY_TOKENS = ('—', '-', '', None)

    def __init__(self, *args, unit_hint="", quantity_name="", **kw):
        super().__init__(*args, **kw)
        self._unit_hint = unit_hint
        self._quantity_name = quantity_name
        from PySide6.QtCore import Qt as _Qt
        self.setContextMenuPolicy(_Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx_menu)

    def setText(self, txt):  # type: ignore[override]
        super().setText(txt if txt is not None else '—')
        state = 'empty' if (txt in self._EMPTY_TOKENS) else 'filled'
        if self.property('valState') != state:
            self.setProperty('valState', state)
            self.style().unpolish(self)
            self.style().polish(self)

    def _show_ctx_menu(self, pos):
        from PySide6.QtWidgets import QMenu, QApplication
        txt = self.text()
        is_empty = txt in self._EMPTY_TOKENS
        menu = QMenu(self)
        act_val = menu.addAction("&Copy value")
        act_val.setEnabled(not is_empty)
        unit_suffix = f"  [{self._unit_hint}]" if self._unit_hint else ""
        act_unit = menu.addAction(f"Copy with &units{unit_suffix}")
        act_unit.setEnabled(not is_empty and bool(self._unit_hint))
        menu.addSeparator()
        act_qty = menu.addAction(
            f"Copy as &assignment ({self._quantity_name or 'value'} = …)")
        act_qty.setEnabled(not is_empty)
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        cb = QApplication.clipboard()
        if chosen is act_val:
            cb.setText(txt)
        elif chosen is act_unit and self._unit_hint:
            cb.setText(f"{txt} {self._unit_hint}")
        elif chosen is act_qty:
            q = self._quantity_name or "value"
            cb.setText(f"{q} = {txt}" + (
                f" [{self._unit_hint}]" if self._unit_hint else ""))


_ENTITY_MAP = {
    '&nbsp;': ' ',
    '&epsilon;': 'ε', '&mu;': 'μ', '&rho;': 'ρ', '&sigma;': 'σ',
    '&phi;': 'φ', '&psi;': 'ψ', '&theta;': 'θ', '&lambda;': 'λ',
    '&alpha;': 'α', '&beta;': 'β', '&gamma;': 'γ', '&delta;': 'δ',
    '&Delta;': 'Δ', '&eta;': 'η', '&kappa;': 'κ', '&pi;': 'π',
    '&tau;': 'τ', '&omega;': 'ω',
    '&middot;': '·', '&plusmn;': '±', '&deg;': '°',
}


def _parse_unit_from_label(text):
    """Extract the unit string inside the last bracket pair of a row label.
    Accepts HTML; strips tags and common entities first. Returns ("K", "T_out")
    for "<i>T</i><sub>out</sub> [K]" etc. Empty unit_hint → no unit token.
    """
    import re as _re_u
    plain = _re_u.sub(r"<[^>]+>", "", text or "")
    for ent, ch in _ENTITY_MAP.items():
        plain = plain.replace(ent, ch)
    plain = plain.strip()
    m = _re_u.search(r"\[([^\[\]]+)\]\s*$", plain)
    unit = m.group(1).strip() if m else ""
    name = (plain[:m.start()] if m else plain).strip().rstrip(",:")
    return unit, name
