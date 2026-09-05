"""A requested zoned problem must fail instead of solving a uniform one."""
from unittest.mock import Mock

import pytest

from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D
from sjtu_tpmshx.domain.compute_config import ComputeConfig, ExtrapPolicy, GeometryConfig, SolverConfig, ZoneInputConfig
from sjtu_tpmshx.solvers.zone_config import ZoneConfig


def test_valid_partial_grid_coverage_is_not_redefined():
    zones = ZoneInputConfig(enabled=True, axis='grid', grid=dict(
        cells=[dict(x0=0.25, x1=0.75, y0=0.2, y1=0.8, L=6, t=0.3)]))
    assert zones.validate() is zones


@pytest.mark.parametrize('dimension', [2, 3])
def test_direct_stage_parse_rejects_invalid_grid(dimension):
    from sjtu_tpmshx.pipelines.stages_2d import _parse_inputs_cfg
    from sjtu_tpmshx.pipelines.stages_3d import _parse_inputs_3d_cfg
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042), solver=SolverConfig(Nz=dimension - 1),
        extrap=ExtrapPolicy(allow=True), zones=ZoneInputConfig(
            enabled=True, axis='grid', grid=dict(
                cells=[dict(x0=1, x1=0, y0=0, y1=1, L=6, t=0.3)])))
    parse = _parse_inputs_cfg if dimension == 2 else _parse_inputs_3d_cfg
    with pytest.raises(ValueError, match='cell 1.*x'):
        parse(cfg)


@pytest.mark.parametrize('axis', ['x', 'y', 'grid'])
def test_supported_air_zones_build_fields(axis):
    from sjtu_tpmshx.pipelines.stages_2d import _parse_inputs_cfg
    grid = dict(cells=[dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)],
                tpms_type='Diamond', k_s=16)
    zones = ZoneInputConfig(enabled=True, axis=axis, grid=grid,
                            config=ZoneConfig.single_zone(6, 0.3, 'Diamond', 16))
    parsed = _parse_inputs_cfg(ComputeConfig(
        zones=zones, solver=SolverConfig(Nx=4, Ny=4),
        extrap=ExtrapPolicy(allow=True)))
    assert parsed['za']['eps_arr'].shape == (4, 4)
    assert parsed['zone_config'] is not None


def test_supported_3d_grid_is_consumed():
    from sjtu_tpmshx.pipelines.stages_3d import _parse_inputs_3d_cfg
    from sjtu_tpmshx.pipelines.grid_3d import _build_zone_fields_3d
    cells = [dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)]
    cfg = ComputeConfig(geometry=GeometryConfig(Lz_m=0.042),
                        solver=SolverConfig(Nx=4, Ny=4, Nz=2),
                        zones=ZoneInputConfig(enabled=True, axis='grid', grid={'cells': cells}),
                        extrap=ExtrapPolicy(allow=True))
    parsed = _parse_inputs_3d_cfg(cfg)
    assert parsed['zone_grid_cells'] == cells
    lengths, thickness, eps = _build_zone_fields_3d(
        parsed['zone_grid_cells'], 4, 4, 2, 0.182, 0.042, 'Diamond', 16, 7, 0.6)
    assert lengths.shape == thickness.shape == eps.shape == (4, 4, 2)
    assert lengths == pytest.approx(6)
    assert thickness == pytest.approx(0.3)


@pytest.mark.parametrize('pipeline,axis,grid', [
    (Pipeline2D, 'y', None), (Pipeline2D, 'grid', None),
    (Pipeline2D, 'grid', {'cells': []}),
    (Pipeline3D, 'y', None), (Pipeline3D, 'grid', None),
    (Pipeline3D, 'grid', {'cells': []}),
])
def test_missing_zones_never_solve_or_finalize(pipeline, axis, grid, monkeypatch):
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042),
        solver=SolverConfig(Nz=2 if pipeline is Pipeline3D else 1),
        extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis=axis, grid=grid))
    pipe = pipeline(cfg)
    solve, finalize = Mock(), Mock()
    monkeypatch.setattr(pipe, 'run_solvers', solve)
    monkeypatch.setattr(pipe, 'finalize', finalize)
    with pytest.raises((ValueError, NotImplementedError), match='[Zz]on|grid'):
        pipe.run()
    solve.assert_not_called()
    finalize.assert_not_called()


@pytest.mark.parametrize('builder', ['compute_properties', 'build_structured_arrays', 'build_grid_arrays'])
def test_zone_builder_error_propagates(builder, monkeypatch):
    zones = ZoneInputConfig(enabled=True,
                            config=ZoneConfig.single_zone(6, 0.3, 'Diamond', 16))
    if builder == 'build_grid_arrays':
        zones.axis = 'grid'
        zones.grid = dict(cells=[dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)],
                          tpms_type='Diamond', k_s=16)
    failure = RuntimeError('zone builder failed')
    monkeypatch.setattr(ZoneConfig, builder, Mock(side_effect=failure))
    if builder == 'build_structured_arrays':
        monkeypatch.setattr(ZoneConfig, 'compute_properties', lambda *a, **kw: None)
    pipe = Pipeline2D(ComputeConfig(zones=zones, extrap=ExtrapPolicy(allow=True)))
    solve, finalize = Mock(), Mock()
    monkeypatch.setattr(pipe, 'run_solvers', solve)
    monkeypatch.setattr(pipe, 'finalize', finalize)
    with pytest.raises(RuntimeError, match='zone builder failed') as caught:
        pipe.run()
    assert caught.value is failure
    solve.assert_not_called()
    finalize.assert_not_called()


@pytest.mark.parametrize('pipeline', [Pipeline2D, Pipeline3D])
@pytest.mark.parametrize('axis', ['x', 'y'])
@pytest.mark.parametrize('start,end', [
    (1, 0), (0.5, 0.5), (-0.1, 1), (0, 1.1),
    (float('nan'), 1), (0, float('inf')),
])
def test_invalid_grid_rectangle_never_solves(pipeline, axis, start, end, monkeypatch):
    cell = dict(x0=0, x1=1, y0=0, y1=1, L=6, t=0.3)
    cell[f'{axis}0'], cell[f'{axis}1'] = start, end
    cfg = ComputeConfig(
        geometry=GeometryConfig(Lz_m=0.042),
        solver=SolverConfig(Nz=2 if pipeline is Pipeline3D else 1),
        extrap=ExtrapPolicy(allow=True),
        zones=ZoneInputConfig(enabled=True, axis='grid', grid=dict(
            cells=[cell], tpms_type='Diamond', k_s=16)))
    pipe = pipeline(cfg)
    solve, finalize = Mock(), Mock()
    monkeypatch.setattr(pipe, 'run_solvers', solve)
    monkeypatch.setattr(pipe, 'finalize', finalize)
    with pytest.raises(ValueError, match=f'cell 1.*{axis}'):
        pipe.run()
    solve.assert_not_called()
    finalize.assert_not_called()
