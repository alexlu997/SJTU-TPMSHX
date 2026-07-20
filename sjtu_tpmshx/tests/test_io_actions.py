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
def win(tmp_path_factory):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(
        ['pytest', '-platform', 'offscreen'])
    # Redirect SessionManager's default base_dir before Main_Menu is built:
    # closeEvent auto-saves the session, and without this the teardown
    # w.close() writes the REAL sjtu_tpmshx/.last_session.json (bug found
    # 2026-07-13). Module-scoped fixture, so patch manually (monkeypatch
    # fixture is function-scoped) and undo after close.
    from _pytest.monkeypatch import MonkeyPatch
    import controllers.session_manager as sm_mod
    mp = MonkeyPatch()
    session_dir = tmp_path_factory.mktemp('session')
    orig_init = sm_mod.SessionManager.__init__

    def _init(self, base_dir=None, parent=None):
        orig_init(self, base_dir=base_dir if base_dir is not None else session_dir,
                  parent=parent)

    mp.setattr(sm_mod.SessionManager, '__init__', _init)
    import main as main_mod
    w = main_mod.Main_Menu()
    yield w
    w.close()
    mp.undo()


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
