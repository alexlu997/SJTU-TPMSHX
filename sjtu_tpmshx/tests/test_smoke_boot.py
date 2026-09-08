"""Keep modal patches isolated from the pytest process and other UI tests."""
import os
import subprocess
import sys


def test_pipeline_smoke_modals():
    subprocess.run([sys.executable, '-c', '''
import ast
import contextlib
import io
import sys
from pathlib import Path

from sjtu_tpmshx.runs import _smoke_boot
assert 'PySide6' not in sys.modules
from PySide6.QtWidgets import QMessageBox
names = ('question', 'warning', 'information', 'exec')
original = [getattr(QMessageBox, name) for name in names]
app = _smoke_boot.get_app()
assert original == [getattr(QMessageBox, name) for name in names]
output = io.StringIO()
with contextlib.redirect_stdout(output):
    _smoke_boot.patch_modals()
    for name in names[:-1]:
        assert getattr(QMessageBox, name)(None, 'title', 'text') == QMessageBox.StandardButton.Yes
    box = QMessageBox()
    assert box.exec() == QMessageBox.StandardButton.Yes
assert output.getvalue() == '  [dialog auto-Yes]\\n' * 3 + '  [instance modal auto-Yes]\\n'

for dimension in ('2d', '3d'):
    path = Path(_smoke_boot.__file__).parent / 'smokes' / f'smoke_ui_{dimension}_pipeline.py'
    module = ast.parse(path.read_text(encoding='utf-8'))
    main = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    assert ast.unparse(main.body[0]) == 'app = _smoke_boot.get_app()'
    assert ast.unparse(main.body[1]) == '_smoke_boot.patch_modals()'
    assert isinstance(main.body[2], ast.ImportFrom) and main.body[2].module == 'sjtu_tpmshx.main'
print('boot import, opt-in patch, four Yes returns, output, and both entry orders PASS')
'''], check=True, timeout=30, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
