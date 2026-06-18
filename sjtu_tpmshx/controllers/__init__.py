"""Controller layer — extracts cross-cutting concerns from main.py god-class.

Per 2026-05-06 audit fix #4 (vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md).

Phase 1: ComputeOrchestrator — solver thread lifecycle. ✅ refactor-p1-done
Phase 2: ResultCache + SessionManager — result + state aggregation.
Phase 3: ThemeManager + SignalRouter — theme + connection lifecycle.
Phase 4: DomainValidator (TODO).
Phase 5: FieldFactory — done (ui/field_factory.py, installed in main.py).
"""
from .compute_config import (
    ComputeConfig,
    FluidConfig,
    GeometryConfig,
    SolverConfig,
    PartialBCConfig,
    ZoneInputConfig,
    ExtrapPolicy,
    FeatureFlags,
)
from .compute_orchestrator import ComputeOrchestrator
from .result_cache import ResultCache
from .session_manager import SessionManager
from .theme_manager import ThemeManager
from .signal_router import SignalRouter

__all__ = [
    'ComputeConfig', 'FluidConfig', 'GeometryConfig', 'SolverConfig',
    'PartialBCConfig', 'ZoneInputConfig', 'ExtrapPolicy', 'FeatureFlags',
    'ComputeOrchestrator', 'ResultCache', 'SessionManager',
    'ThemeManager', 'SignalRouter',
]
