"""SJTU-TPMSHX package init.

The canonical import style is package-qualified — ``from sjtu_tpmshx.solvers
import ...`` — everywhere: library internals, tests, scripts, tools. The
legacy top-level style (``from solvers import ...``) and the per-file
sys.path bootstrap blocks that supported it were retired by openspec change
``p18b-import-style-migration`` (W0–F2, 2026-07-21). This file briefly hosted
the transitional import-identity shim (meta-path finder aliasing both styles
to one module object); with the migration complete, the shim is gone and no
import-time side effects remain here. Install the package (``pip install -e
.``) or run via the repo root to resolve ``sjtu_tpmshx``.
"""
