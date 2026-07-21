"""SJTU-TPMSHX package init — P1.8b transitional import-identity shim (W0).

Until P1.8b lands, the library internally uses TOP-LEVEL import style
(``from solvers import ...``), historically supported by per-file sys.path
bootstrap blocks. ``solvers.X`` and ``sjtu_tpmshx.solvers.X`` are DIFFERENT
module objects to CPython (two sys.modules keys), so mixing styles in one
process duplicates module-level state — warn-once registries
(nu_correlations._EXTRAP_WARNED, predict._CHOKE_WARNED), logutil's logger
wiring, field caches. This init makes both styles resolve to the SAME object:

1. self-bootstrap — the package dir goes on sys.path (the ONE sanctioned
   bootstrap during the migration; caller-side blocks are deleted wave by
   wave, and this whole shim dies in W_final);
2. an identity meta-path finder — any ``sjtu_tpmshx.X[.Y...]`` import is
   aliased to the canonical top-level ``X[.Y...]`` object. The parent
   package init always runs before any submodule import, so no package-style
   import can bypass the finder.

Design + wave plan: openspec/changes/p18b-import-style-migration/design.md.
Remove in W_final only, together with the library-internal rewrite.
"""
import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent

# (1) Self-bootstrap. insert(0) matches what every legacy per-file bootstrap
# block already does, so the shadowing order of generic names (core, ui, ...)
# is unchanged from the status quo.
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

# Aliasable top-level entities = real subpackages (dir with __init__.py) and
# top-level modules of this package. Computed dynamically so W1..Wn need no
# edits here. tests/ has no __init__.py and thus stays out by construction —
# pytest imports test files under their own top-level names, and aliasing a
# generic name like 'tests' invites collisions.
_TOP_LEVEL = frozenset(
    p.stem if p.is_file() else p.name
    for p in _PKG_DIR.iterdir()
    if (p.is_file() and p.suffix == '.py' and p.stem != '__init__')
    or (p.is_dir() and (p / '__init__.py').is_file())
)


class _AliasLoader(importlib.abc.Loader):
    """Loader that hands back an EXISTING module object.

    create_module returns the canonical top-level module; exec_module never
    re-runs the body (solvers/__init__'s threads.init_from_env() etc. stay
    single-shot) — it only restores the canonical ``__spec__``/``__loader__``,
    which the import machinery rebinds to the alias spec between
    create_module and exec_module (measured on CPython 3.12: __name__ and
    __package__ survive, __spec__ does not; a clobbered spec silently turns
    ``importlib.reload(solvers)`` into a no-op through this loader).
    """

    def __init__(self, target):
        self._target = target
        self._spec = getattr(target, '__spec__', None)
        self._loader = getattr(target, '__loader__', None)

    def create_module(self, spec):
        return self._target

    def exec_module(self, module):
        if self._spec is not None:
            module.__spec__ = self._spec
        if self._loader is not None:
            module.__loader__ = self._loader


class _IdentityFinder(importlib.abc.MetaPathFinder):
    """Alias ``sjtu_tpmshx.<rest>`` to the top-level ``<rest>`` module.

    Must sit at the FRONT of sys.meta_path: for ``import sjtu_tpmshx.solvers.x``
    the machinery resolves parents first, and without interception PathFinder
    would exec solvers/x.py a second time under the package name.
    """

    # Idempotency marker checked as an ATTRIBUTE, not via isinstance —
    # importlib.reload() of this module rebinds the class object, and an
    # isinstance guard against the new class misses instances of the old one.
    _P18B_IDENTITY_FINDER = True

    _PREFIX = __name__ + '.'

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self._PREFIX):
            return None
        rest = fullname[len(self._PREFIX):]
        if rest.split('.', 1)[0] not in _TOP_LEVEL:
            return None  # e.g. sjtu_tpmshx.tests.* → normal namespace traversal
        canonical = importlib.import_module(rest)
        spec = importlib.util.spec_from_loader(
            fullname, _AliasLoader(canonical))
        # Keep dotted traversal working when callers go one level deeper via
        # this spec (submodule search re-enters the finder anyway).
        if hasattr(canonical, '__path__'):
            spec.submodule_search_locations = list(canonical.__path__)
        return spec


if not any(getattr(type(f), '_P18B_IDENTITY_FINDER', False)
           for f in sys.meta_path):
    sys.meta_path.insert(0, _IdentityFinder())
