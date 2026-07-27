"""Single-source application version (P1.9, 2026-07-20).

Previously ``main.py`` owned ``__version__`` and UI widgets imported the
COMPOSITION ROOT just to display it (the ui->main cycle edge in the import
audit). This leaf module has no imports, so anything may read it from either
convention (``_version`` in-repo, ``sjtu_tpmshx._version`` installed) — a
pure-constant module is the one place the dual-import duplication is
harmless. pyproject.toml reads it via ``[tool.setuptools.dynamic]``.
"""

__version__ = "1.5.0"
