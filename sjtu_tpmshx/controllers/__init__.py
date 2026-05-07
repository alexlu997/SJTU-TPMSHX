"""Controller layer — extracts cross-cutting concerns from main.py god-class.

Per 2026-05-06 audit fix #4 (vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md).

Phase 1: ComputeOrchestrator — solver thread lifecycle. ✅ refactor-p1-done
Phase 2: ResultCache + SessionManager — result + state aggregation.
Phase 3: ThemeManager + SignalRouter (TODO).
Phase 4: DomainValidator (TODO).
Phase 5: FieldFactory (TODO).
"""
from .compute_orchestrator import ComputeOrchestrator
from .result_cache import ResultCache
from .session_manager import SessionManager

__all__ = ['ComputeOrchestrator', 'ResultCache', 'SessionManager']
