"""Controller layer — extracts cross-cutting concerns from main.py god-class.

Per 2026-05-06 audit fix #4 (vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md).

Phase 1: ComputeOrchestrator — solver thread lifecycle. ✅ refactor-p1-done
Phase 2: ResultCache + SessionManager — result + state aggregation.
Phase 3: ThemeManager + SignalRouter — theme + connection lifecycle.
Phase 4: DomainValidator — done (domain/validator.py).
Phase 5: FieldFactory — done (ui/field_factory.py, installed in main.py).
"""
# contracts-layer split (2026-07-02): the compute contracts moved to
# domain.compute_config / domain.compute_result; the window-harvest adapter
# to ui.window_config; ThemeManager to ui.theme_manager. This package keeps
# the orchestration/state controllers only.
# P1.8 (2026-07-20): lazy re-exports (PEP 562). The four names below pull
# PySide6 at import time; eager importing them made `import
# controllers.compute_pipeline` (the Qt-FREE headless seam) drag Qt into
# every headless consumer (CLI, server scripts). `from controllers import
# ComputeOrchestrator` still works exactly as before — Qt now loads when
# the name is touched, not when the package is.
_LAZY = {
    'ComputeOrchestrator': '.compute_orchestrator',
    'ResultCache': '.result_cache',
    'SessionManager': '.session_manager',
    'SignalRouter': '.signal_router',
}


def __getattr__(name):
    if name in _LAZY:
        from importlib import import_module
        return getattr(import_module(_LAZY[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals()) + list(_LAZY))

__all__ = [
    'ComputeOrchestrator', 'ResultCache', 'SessionManager', 'SignalRouter',
]
