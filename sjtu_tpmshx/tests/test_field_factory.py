"""Unit tests for ui.field_factory.FieldFactory.

Phase 5 of 2026-05-06 main.py refactor (audit fix #4). Tests are Qt-aware
(they instantiate widgets) but use the offscreen platform; no live
window or theme switch.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLineEdit, QLabel, QVBoxLayout, QWidget,
    QComboBox,
)

from ui.theme_manager import ThemeManager
from ui.field_factory import (
    FieldFactory, default_factory, set_default_factory,
)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def factory():
    _app()
    return FieldFactory(ThemeManager())


@pytest.fixture(autouse=True)
def _reset_default_factory():
    """Each test starts with no installed default factory."""
    set_default_factory(None)
    yield
    set_default_factory(None)


# ---------------------------------------------------------------- atoms


def test_label_returns_qlabel_with_text(factory):
    lbl = factory.label('hello')
    assert isinstance(lbl, QLabel)
    assert lbl.text() == 'hello'
    assert lbl.textFormat() == Qt.TextFormat.RichText


def test_label_plain_mode():
    _app()
    f = FieldFactory(ThemeManager())
    lbl = f.label('<b>raw</b>', rich=False)
    assert lbl.textFormat() != Qt.TextFormat.RichText


def test_line_edit_default_text(factory):
    le = factory.line_edit('0.080')
    assert isinstance(le, QLineEdit)
    assert le.text() == '0.080'


def test_line_edit_tooltip_and_placeholder(factory):
    le = factory.line_edit('', tooltip='hint', placeholder='ph')
    assert le.toolTip() == 'hint'
    assert le.placeholderText() == 'ph'


def test_result_label_starts_empty(factory):
    val = factory.result_label(unit_hint='K', quantity_name='T_in')
    assert val.text() == '—'
    assert val.property('valState') == 'empty'


def test_result_label_set_text_flips_to_filled(factory):
    val = factory.result_label(unit_hint='K')
    val.setText('298.15')
    assert val.property('valState') == 'filled'


# ---------------------------------------------------------------- rows


def test_row_adds_two_cells(factory):
    host = QWidget()
    g = QGridLayout(host)
    le = factory.row(g, 0, 'L [m]', '0.080')
    assert isinstance(le, QLineEdit)
    assert le.text() == '0.080'
    assert g.itemAtPosition(0, 0) is not None
    assert g.itemAtPosition(0, 1) is not None
    # Label cell holds a QLabel
    assert isinstance(g.itemAtPosition(0, 0).widget(), QLabel)


def test_res_row_parses_unit_hint(factory):
    host = QWidget()
    g = QGridLayout(host)
    val = factory.res_row(g, 0, 'T<sub>in</sub> [K]')
    assert val.property('valState') == 'empty'
    # _ResultLabel records the unit hint
    assert val._unit_hint == 'K'


def test_add_row_returns_passed_widget(factory):
    host = QWidget()
    g = QGridLayout(host)
    combo = QComboBox()
    out = factory.add_row(g, 0, 'TPMS', combo)
    assert out is combo
    assert g.itemAtPosition(0, 1).widget() is combo


# ---------------------------------------------------------------- section


def test_section_returns_grid_and_container(factory):
    host = QWidget()
    parent_lay = QVBoxLayout(host)
    g, container = factory.section(parent_lay, 'Geometry',
                                     'color:white;', 'background:#222;')
    assert isinstance(g, QGridLayout)
    assert isinstance(container, QWidget)
    # Section title margins/spacing match legacy contract
    m = g.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (12, 10, 12, 10)
    assert g.verticalSpacing() == 8
    assert g.horizontalSpacing() == 10


# ---------------------------------------------------------------- singleton


def test_default_factory_lazy_creates():
    _app()
    set_default_factory(None)
    f = default_factory()
    assert isinstance(f, FieldFactory)
    # Same instance returned next call
    assert default_factory() is f


def test_set_default_factory_overrides():
    _app()
    custom = FieldFactory(ThemeManager())
    set_default_factory(custom)
    assert default_factory() is custom


# ---------------------------------------------------------------- repr


def test_repr_safe(factory):
    s = repr(factory)
    assert 'FieldFactory' in s
