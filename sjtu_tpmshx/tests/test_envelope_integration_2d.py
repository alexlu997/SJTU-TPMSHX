"""End-to-end compressible validity gate in the 2D pipeline (_run_solvers).

Unlike the 3D path (outlet-anchored P datum -> dP>P_in drives the outlet to
vacuum -> supersonic blow-up), the 2D path is inlet-anchored: a large dP raises
the inlet absolute pressure instead, so the mass-flux inlet keeps v bounded and
the solve stays physical. The gate therefore reports valid even at high dP (no
false choke flag); it only fires on a genuinely non-physical field. These tests
pin the wiring: the result carries the gate keys, and a high-dP case is NOT
falsely flagged.
"""
import sys
from pathlib import Path
from dataclasses import replace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controllers.compute_config import ComputeConfig
from controllers.compute_pipeline import Pipeline2D


def _run_2d(u, L=0.182, Nx=20, Ny=20):
    base = ComputeConfig()
    cfg = replace(
        base,
        geometry=replace(base.geometry, t_wall_mm=0.5, L_dom_m=L),
        fluid_A=replace(base.fluid_A, u_mps=u),
        solver=replace(base.solver, Nx=Nx, Ny=Ny, max_outer_ltne=2))
    pipe = Pipeline2D(cfg)
    fields = pipe.build_fields()
    return pipe.run_solvers(fields)


def test_2d_in_envelope_reports_valid_with_gate_keys():
    raw = _run_2d(u=5.0, L=0.182)
    assert raw['envelope_valid'] is True
    assert raw['p_clip_hits'] == 0
    assert raw['envelope_reasons'] == []


def test_2d_high_dp_inlet_anchored_not_falsely_flagged():
    # dP ~ 3x P_in here, but the inlet-anchored datum keeps the field physical.
    raw = _run_2d(u=40.0, L=0.7)
    assert raw['envelope_valid'] is True, raw['envelope_reasons']
    assert raw['dP_A'] > raw_pin(), "expected a large dP for this stress case"


def raw_pin():
    return ComputeConfig().fluid_A.P_in_Pa  # 101325 Pa
