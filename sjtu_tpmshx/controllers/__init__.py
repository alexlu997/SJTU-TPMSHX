"""Controller layer — extracts cross-cutting concerns from main.py god-class.

Per 2026-05-06 audit fix #4 (vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md).

Phase 1: ComputeOrchestrator — solver thread lifecycle. ✅ refactor-p1-done
Phase 2: ResultCache + SessionManager — result + state aggregation.
Phase 3: ThemeManager + SignalRouter — theme + connection lifecycle.
Phase 4: DomainValidator (TODO).
Phase 5: FieldFactory — done (ui/field_factory.py, installed in main.py).
"""
# contracts-layer split (2026-07-02): the compute contracts moved to
# domain.compute_config / domain.compute_result; the window-harvest adapter
# to ui.window_config; ThemeManager to ui.theme_manager. This package keeps
# the orchestration/state controllers only.
from .compute_orchestrator import ComputeOrchestrator
from .result_cache import ResultCache
from .session_manager import SessionManager
from .signal_router import SignalRouter

__all__ = [
    'ComputeOrchestrator', 'ResultCache', 'SessionManager', 'SignalRouter',
]
