"""P1.8b W0 — import-identity shim contract (openspec p18b-import-style-migration).

While the migration is in flight, BOTH import styles must yield the SAME
module object, or module-level state (warn-once registries, logutil wiring,
field caches) silently duplicates. These tests pin the shim's whole reason
to exist; they must stay green through every W1..Wn wave. W_final replaces
them with "shim removed" assertions (see tasks.md).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPO = ROOT.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_package_and_toplevel_style_share_module_object():
    import solvers
    import sjtu_tpmshx.solvers as pkg_solvers
    assert pkg_solvers is solvers, (
        "sjtu_tpmshx.solvers and solvers are different module objects — the "
        "P1.8b identity shim is broken; mixing styles now duplicates state")


def test_identity_holds_at_depth():
    from solvers import envelope as top_env
    from sjtu_tpmshx.solvers import envelope as pkg_env
    assert pkg_env is top_env

    import df_surrogate.predict as top_pred
    import sjtu_tpmshx.df_surrogate.predict as pkg_pred
    assert pkg_pred is top_pred

    import logutil as top_log
    import sjtu_tpmshx.logutil as pkg_log
    assert pkg_log is top_log, (
        "dual logutil = dual tpmshx.* logger wiring (design.md D3)")


def test_warn_registries_are_shared_state():
    """The concrete hazard the shim kills: one registry set, not two."""
    import solvers.nu_correlations as top_nc
    import sjtu_tpmshx.solvers.nu_correlations as pkg_nc
    assert pkg_nc._EXTRAP_WARNED is top_nc._EXTRAP_WARNED

    import df_surrogate.predict as top_dp
    import sjtu_tpmshx.df_surrogate.predict as pkg_dp
    assert pkg_dp._CHOKE_WARNED is top_dp._CHOKE_WARNED


def test_finder_installed_once_and_first():
    import importlib
    import sjtu_tpmshx
    importlib.reload(sjtu_tpmshx)  # re-running init must not stack finders
    finders = [f for f in sys.meta_path
               if type(f).__name__ == '_IdentityFinder']
    assert len(finders) == 1, f"expected exactly one finder, got {len(finders)}"
    assert type(sys.meta_path[0]).__name__ == '_IdentityFinder', (
        "finder must sit at the FRONT of sys.meta_path or PathFinder execs "
        "submodules a second time under the package name (design.md D2)")


def test_module_body_not_executed_twice(monkeypatch):
    """_AliasLoader.exec_module is a no-op — solvers/__init__ side effects
    (threads.init_from_env) must not re-run on package-style import."""
    import solvers
    sentinel = object()
    monkeypatch.setattr(solvers, '_P18B_SENTINEL', sentinel, raising=False)
    sys.modules.pop('sjtu_tpmshx.solvers', None)  # force finder path anew
    import sjtu_tpmshx.solvers as pkg_solvers
    assert getattr(pkg_solvers, '_P18B_SENTINEL', None) is sentinel, (
        "package-style import re-executed the module body (sentinel lost)")


def test_canonical_spec_survives_aliasing():
    """The import machinery rebinds module.__spec__ to the alias spec between
    create_module and exec_module; the loader must restore the canonical one
    or importlib.reload(solvers) silently degrades to a no-op."""
    import solvers
    sys.modules.pop('sjtu_tpmshx.solvers', None)
    import sjtu_tpmshx.solvers  # noqa: F401  (side effect under test)
    assert solvers.__spec__.name == 'solvers'
    assert solvers.__name__ == 'solvers'


def test_tests_namespace_not_aliased():
    """tests/ has no __init__.py and must NOT be aliased to a generic
    top-level 'tests' name (collision surface)."""
    import sjtu_tpmshx
    assert 'tests' not in sjtu_tpmshx._TOP_LEVEL
