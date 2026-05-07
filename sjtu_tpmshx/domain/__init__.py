"""Domain logic — pure functions for TPMS HX validation + grid suggestion.

Phase 4 of 2026-05-06 main.py refactor (audit fix #4). Extracts business
logic that was previously inlined in ``Main_Menu`` methods (compute_tpms,
_auto_fill_fluid, _fluid_config, _attach_input_validators, ...) into
**Qt-free** functions taking dict / scalar input and returning structured
results + a list of human-readable warnings.

Why
---
Previously every domain check was tied to a widget — ``self.le_L.text()``
was read inline, errors were painted directly via ``setStyleSheet`` /
``setToolTip``. This meant:

* No headless tests for the actual logic (only widget existence in
  ``test_main_smoke.py``).
* ``validate_shanghai_*.py`` had to re-implement the same fluid-config /
  geometry-suggestion arithmetic.
* Same rule (e.g. ``t/L`` extrapolation warning) lived in 2-3 places
  with subtle drift.

After P4, ``main.py`` collects widget values into a dict, calls the
appropriate domain function, and renders the resulting warnings — but
the rule itself lives here, can be unit-tested without Qt, and can be
reused from validation scripts.

API surface (this module just re-exports):

    suggest_grid_2d, suggest_grid_3d  — grid-from-D_h heuristic
    validate_geometry                 — t/L ratio + range warnings
    compute_volumetric_htc            — A_0 * H_sf
    wall_for_dir, cross_axes_for_dir  — direction → axis labels
    parse_unit_value                  — natural-language unit parser
    validate_pipe_config              — pipe BC dict sanity check
    geometry_extrapolation_warning    — Shanghai t=0.6 / L=7 etc.
"""
from __future__ import annotations

from .validator import (
    suggest_grid_2d,
    suggest_grid_3d,
    validate_geometry,
    compute_volumetric_htc,
    wall_for_dir,
    cross_axes_for_dir,
    parse_unit_value,
    validate_pipe_config,
    geometry_extrapolation_warning,
    Warning as DomainWarning,
)

__all__ = [
    'suggest_grid_2d',
    'suggest_grid_3d',
    'validate_geometry',
    'compute_volumetric_htc',
    'wall_for_dir',
    'cross_axes_for_dir',
    'parse_unit_value',
    'validate_pipe_config',
    'geometry_extrapolation_warning',
    'DomainWarning',
]
