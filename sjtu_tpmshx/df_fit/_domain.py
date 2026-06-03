"""Single source of truth for the ConstDF-v1 surrogate training domain.

Re-calibrating the surrogate = edit these constants HERE (nothing else).
Consumed by df_fit.surrogate_domain, design.optimize, solvers.field_param
(continuous convex hull) and domain.validator (discrete training nodes).

Pure constants, zero imports — importing this module can never trigger a
package import cycle.
"""
from __future__ import annotations

# Continuous convex hull (extrapolation-guard bounds).
TRAIN_L = (4.0, 8.0)          # unit cell size L [mm]
TRAIN_T = (0.3, 0.5)          # wall thickness t [mm]
TRAIN_RE = (400.0, 16000.0)   # Reynolds ρ·u·D_h/μ

# Discrete training grid nodes (the geometries actually fitted).
TRAIN_L_NODES = (4.0, 5.0, 6.0, 8.0)
TRAIN_T_NODES = (0.3, 0.4, 0.5)
