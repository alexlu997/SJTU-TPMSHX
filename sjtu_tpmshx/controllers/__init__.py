"""Controller layer — extracts cross-cutting concerns from main.py god-class.

Per 2026-05-06 audit fix #4 (vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md).

Phase 1: ComputeOrchestrator — solver thread lifecycle.
Phase 2: ResultCache + SessionManager (TODO).
"""
from .compute_orchestrator import ComputeOrchestrator

__all__ = ['ComputeOrchestrator']
