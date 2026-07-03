"""IOActionsMixin locks (openspec maintainability-closeout, 2026-07-03).

save_config/load_config JSON round-trip was 0%-tested despite being the
user's config persistence path — a broken key silently loses a field.
Offscreen Main_Menu fixture mirrors test_ui_layout_hygiene.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def win():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(
        ['pytest', '-platform', 'offscreen'])
    import main as main_mod
    w = main_mod.Main_Menu()
    yield w
    w.close()


def test_save_load_config_roundtrip(tmp_path, monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog
    cfg_path = str(tmp_path / 'cfg.json')

    win.le_Lcell.setText('6.5')
    win.le_t.setText('0.45')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        staticmethod(lambda *a, **k: (cfg_path, 'json')))
    win.save_config()

    data = json.loads(Path(cfg_path).read_text(encoding='utf-8'))
    assert data['L_cell'] == '6.5'
    assert data['t'] == '0.45'

    # Perturb, then load back — fields must restore.
    win.le_Lcell.setText('9.9')
    win.le_t.setText('0.9')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        staticmethod(lambda *a, **k: (cfg_path, 'json')))
    win.load_config()
    assert win.le_Lcell.text() == '6.5'
    assert win.le_t.text() == '0.45'


def test_load_config_cancel_is_noop(monkeypatch, win):
    from PySide6.QtWidgets import QFileDialog
    win.le_Lcell.setText('7.0')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName',
                        staticmethod(lambda *a, **k: ('', '')))
    win.load_config()
    assert win.le_Lcell.text() == '7.0'


def test_export_results_no_data_shows_dialog(monkeypatch, win):
    """Without results the export path must short-circuit on the info
    dialog — not crash, not write a file."""
    from PySide6.QtWidgets import QMessageBox
    hits = []
    monkeypatch.setattr(QMessageBox, 'information',
                        staticmethod(lambda *a, **k: hits.append(a)))
    # Fresh module-scoped window: no compute has run, so both the 2D
    # cache and _result_3d are empty by construction.
    win._export_results()
    assert hits, 'expected the No Results dialog'
