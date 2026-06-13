"""pipelines/ — Qt-free compute stage functions behind the ComputePipeline.

Holds the per-dimension compute stacks (``stages_2d``, ``stages_3d``) that
``controllers.compute_pipeline.Pipeline2D/Pipeline3D`` drive through their
parse → build_fields → run_solvers → finalize phases.  Extracted from
``runs/`` in batch-3 (2026-06-13) to fix the controllers→runs layer
inversion: ``controllers/`` and ``ui/`` may import ``pipelines/`` but
``pipelines/`` imports nothing from ``runs/``.
"""
