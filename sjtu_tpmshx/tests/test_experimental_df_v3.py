import numpy as np
import pytest
from pathlib import Path

from sjtu_tpmshx.df_surrogate.experimental_correction import (
    apply_correction, correction_scale)
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF
from sjtu_tpmshx.domain.compute_config import (
    ComputeConfig, FluidConfig, GeometryConfig, PartialBCConfig, SolverConfig)
from sjtu_tpmshx.solvers.tpms_calc import geometry


def _base(tpms, L, t):
    eps_f = geometry(tpms, L, t, 16.0)["epsilon"] / 2.0
    return predict_K_cF(tpms, L, t, eps_f)


def _air_cfg(**kwargs):
    cfg = ComputeConfig(
        fluid_A=FluidConfig(type="air"),
        fluid_B=FluidConfig(type="air"),
        geometry=GeometryConfig(tpms="Gyroid", L_cell_mm=7.0,
                                t_wall_mm=0.4),
        df_mode="experimental",
    )
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return cfg


def test_default_cfd_mode_keeps_production_predictor_values():
    cfg = ComputeConfig()
    before = _base("Gyroid", 7.0, 0.4)
    cfg.validate()
    after = _base("Gyroid", 7.0, 0.4)
    assert cfg.df_mode == "cfd_smooth"
    assert before == after


def test_experiment_mode_json_roundtrip(tmp_path):
    cfg = _air_cfg()
    path = tmp_path / "cfg.json"
    cfg.to_json(path)
    assert ComputeConfig.from_json(path) == cfg


def test_air_scalar_and_array_apply_the_same_fixed_scale():
    K0, cF0 = _base("Gyroid", 7.0, 0.4)
    Ks, cFs, meta = apply_correction(
        "Gyroid", "air", 7.0, 0.4, K0, cF0)
    Ka, cFa, _ = apply_correction(
        "Gyroid", "air", np.full((3, 2), 7.0), np.full((3, 2), 0.4),
        np.full((3, 2), K0), np.full((3, 2), cF0))
    assert np.array_equal(Ka, np.full((3, 2), Ks))
    assert np.array_equal(cFa, np.full((3, 2), cFs))
    assert meta["base_K"] == K0 and meta["applied_K"] == K0
    assert meta["campaign"] == "air-specimen-friction"
    assert meta["scope"] == "core-calibrated"


def test_air_domain_does_not_extrapolate_t06():
    with pytest.raises(ValueError, match="t=0.6"):
        correction_scale("Diamond", "air", 7.0, 0.55)


def _water_air_cfg(*, tpms="Diamond", water_u=0.15, air_u=20.0,
                   fluid_A="water", fluid_B="air"):
    speed = {"water": water_u, "air": air_u}
    return ComputeConfig(
        fluid_A=FluidConfig(type=fluid_A, u_mps=speed[fluid_A]),
        fluid_B=FluidConfig(type=fluid_B, u_mps=speed[fluid_B]),
        geometry=GeometryConfig(tpms=tpms, L_cell_mm=7.0,
                                t_wall_mm=0.6, L_dom_m=0.182,
                                H_dom_m=0.042, Lz_m=0.042),
        solver=SolverConfig(Nx=4, Ny=4, Nz=2),
        bc_A=PartialBCConfig(dir=0), bc_B=PartialBCConfig(dir=1),
        df_mode="experimental")


def test_water_hx_velocity_window_is_explicit():
    _water_air_cfg().validate()
    with pytest.raises(ValueError, match="active side A.*0.1<=u"):
        _water_air_cfg(water_u=0.09).validate()
    with pytest.raises(ValueError, match="active side A.*0.254055"):
        _water_air_cfg(water_u=0.26).validate()
    with pytest.raises(ValueError, match="active side B.*22.7599"):
        _water_air_cfg(air_u=23.0).validate()


def test_water_hx_requires_matching_domain_but_allows_local_ports():
    cfg = _water_air_cfg()
    cfg.geometry.L_dom_m = 0.18
    with pytest.raises(ValueError, match="matching 0.182 x 0.042"):
        cfg.validate()
    cfg = _water_air_cfg()
    cfg.bc_B = PartialBCConfig(
        dir=1, in_ctr=0.012, in_w=0.012,
        out_ctr=0.030, out_w=0.012,
        in_z_ctr=0.012, in_z_w=0.012,
        out_z_ctr=0.030, out_z_w=0.012)
    cfg.validate()


_HX_FLUID = {
    "air": dict(u_mps=20.0, T_in_K=400.0, P_in_Pa=200_000.0),
    "water": dict(u_mps=0.15, T_in_K=300.0, P_in_Pa=2_000_000.0),
    "sco2": dict(u_mps=0.3, T_in_K=500.0, P_in_Pa=12_000_000.0),
}


def _experimental_hx_cfg(fluid_A, fluid_B, *, dir_A=0, dir_B=1, nz=2):
    return ComputeConfig(
        fluid_A=FluidConfig(type=fluid_A, **_HX_FLUID[fluid_A]),
        fluid_B=FluidConfig(type=fluid_B, **_HX_FLUID[fluid_B]),
        geometry=GeometryConfig(
            tpms="Diamond", L_cell_mm=7.0, t_wall_mm=0.6,
            L_dom_m=0.182, H_dom_m=0.042,
            Lz_m=0.042 if nz > 1 else None),
        solver=SolverConfig(Nx=4, Ny=4, Nz=nz),
        bc_A=PartialBCConfig(dir=dir_A),
        bc_B=PartialBCConfig(dir=dir_B),
        df_mode="experimental")


@pytest.mark.parametrize(
    "fluid_A,fluid_B",
    [(a, b) for a in _HX_FLUID for b in _HX_FLUID],
)
def test_experimental_hx_accepts_all_ordered_fluid_pairs(fluid_A, fluid_B):
    _experimental_hx_cfg(fluid_A, fluid_B).validate()


def _sco2_cfg(*, dir_B=1, local_port=False):
    width = 0.02 if local_port else 0.0
    return ComputeConfig(
        fluid_A=FluidConfig(type="sco2", T_in_K=500.0, P_in_Pa=12e6),
        fluid_B=FluidConfig(type="sco2", T_in_K=300.0, P_in_Pa=12e6),
        geometry=GeometryConfig(tpms="Diamond", L_cell_mm=7.0,
                                t_wall_mm=0.6, L_dom_m=0.182,
                                H_dom_m=0.042, Lz_m=0.042),
        solver=SolverConfig(Nx=4, Ny=4, Nz=2),
        bc_A=PartialBCConfig(dir=0, in_ctr=0.021, in_w=width,
                             out_ctr=0.021, out_w=width),
        bc_B=PartialBCConfig(dir=dir_B, in_ctr=0.021, in_w=width,
                             out_ctr=0.021, out_w=width),
        df_mode="experimental")


@pytest.mark.parametrize("direction", range(6))
def test_sco2_hx_effective_allows_local_ports_in_every_3d_direction(direction):
    _sco2_cfg(dir_B=direction, local_port=True).validate()


def test_side_scales_are_selected_independently_not_averaged():
    _, water_sF, water_campaign, _ = correction_scale(
        "Diamond", "water", 7.0, 0.6, 0.15)
    _, air_sF, air_campaign, _ = correction_scale(
        "Diamond", "air", 7.0, 0.6, 20.0)
    assert float(np.asarray(water_sF)) != float(np.asarray(air_sF))
    assert water_campaign == air_campaign == "water-air-hx-7-6"


@pytest.mark.slow
def test_2d_and_3d_apply_the_same_coefficients_once():
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D

    def cfg(nz):
        return ComputeConfig(
            fluid_A=FluidConfig(type="air", u_mps=2, T_in_K=400,
                                P_in_Pa=150000),
            fluid_B=FluidConfig(type="air", u_mps=2, T_in_K=300,
                                P_in_Pa=150000),
            geometry=GeometryConfig(
                tpms="Gyroid", L_cell_mm=7, t_wall_mm=0.4,
                L_dom_m=0.04, H_dom_m=0.02,
                Lz_m=0.02 if nz > 1 else None),
            solver=SolverConfig(Nx=4, Ny=4, Nz=nz, max_outer_ltne=2,
                                max_iter_simple=100),
            bc_A=PartialBCConfig(dir=0), bc_B=PartialBCConfig(dir=1),
            df_mode="experimental")

    m2 = Pipeline2D(cfg(1)).run().metadata["darcy_forchheimer"]
    m3 = Pipeline3D(cfg(2)).run().metadata["darcy_forchheimer"]
    c2 = m2["A"]["applied_cF"]
    c3 = m3["A"]["applied_cF"]["min"]
    assert c2 == c3
    assert c2 / m2["A"]["base_cF"] == m2["A"]["scale_F"]
    assert m2["A"] == m2["B"] and m3["A"] == m3["B"]


@pytest.mark.slow
def test_water_air_2d_and_3d_use_separate_hx_coefficients_once():
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D, Pipeline3D

    def cfg(nz):
        if nz == 1:
            bc_A = PartialBCConfig(
                dir=2, in_ctr=0.091, in_w=0.091,
                out_ctr=0.091, out_w=0.091)
            bc_B = PartialBCConfig(
                dir=3, in_ctr=0.091, in_w=0.091,
                out_ctr=0.091, out_w=0.091)
        else:
            bc_A = PartialBCConfig(
                dir=4, in_ctr=0.091, in_w=0.091,
                out_ctr=0.091, out_w=0.091,
                in_z_ctr=0.021, in_z_w=0.021,
                out_z_ctr=0.021, out_z_w=0.021)
            bc_B = PartialBCConfig(
                dir=5, in_ctr=0.091, in_w=0.091,
                out_ctr=0.091, out_w=0.091,
                in_z_ctr=0.021, in_z_w=0.021,
                out_z_ctr=0.021, out_z_w=0.021)
        return ComputeConfig(
            fluid_A=FluidConfig(type="water", u_mps=0.15, T_in_K=300.0,
                                P_in_Pa=150000.0),
            fluid_B=FluidConfig(type="air", u_mps=20.0, T_in_K=400.0,
                                P_in_Pa=150000.0),
            geometry=GeometryConfig(
                tpms="Diamond", L_cell_mm=7.0, t_wall_mm=0.6,
                L_dom_m=0.182, H_dom_m=0.042,
                Lz_m=0.042 if nz > 1 else None),
            solver=SolverConfig(Nx=4, Ny=4, Nz=nz, max_outer_ltne=2,
                                max_iter_simple=100),
            bc_A=bc_A,
            bc_B=bc_B,
            df_mode="experimental")

    m2 = Pipeline2D(cfg(1)).run().metadata["darcy_forchheimer"]
    m3 = Pipeline3D(cfg(2)).run().metadata["darcy_forchheimer"]
    assert m2["A"]["scale_F"] == pytest.approx(4.892779870412083)
    assert m2["B"]["scale_F"] == pytest.approx(1.8024228153853061)
    assert m3["A"]["scale_F"] == pytest.approx(m2["A"]["scale_F"])
    assert m3["B"]["scale_F"] == pytest.approx(m2["B"]["scale_F"])
    for side in ("A", "B"):
        assert (m2[side]["applied_cF"] / m2[side]["base_cF"]
                == pytest.approx(m2[side]["scale_F"]))
        assert m2[side]["campaign"] == "water-air-hx-7-6"
        assert m3[side]["campaign"] == "water-air-hx-7-6"


_RAW = Path(__file__).resolve().parents[2] / "data" / "raw_data"


@pytest.mark.skipif(not (_RAW / "试验记录表_整理版.xlsx").exists(),
                    reason="private calibration data unavailable")
def test_reviewed_experiment_pressure_error_gates():
    from sjtu_tpmshx.validation.df_refit.fit_experimental_effective import (
        fit_air, fit_sco2)
    air, _ = fit_air()
    sco2, _ = fit_sco2()
    approved = air[air.status == "approved"]
    assert approved.rmsre.max() <= 0.10
    assert approved.bias.abs().max() <= 0.10
    assert sco2.rmsre.max() <= 0.10
    assert sco2.bias.abs().max() <= 0.10


@pytest.mark.skipif(not (_RAW / "7-6-Water-dp.xlsx").exists(),
                    reason="private water+air HX data unavailable")
def test_water_hx_quality_flags_and_frozen_candidates():
    from sjtu_tpmshx.validation.df_refit.fit_experimental_effective import (
        fit_water_hx)

    summary, quality = fit_water_hx()
    expected = {
        "Diamond": (9, 4.892779870412083, 0.06838926916238654),
        "Gyroid": (11, 4.198913430360186, 0.009341008837567524),
    }
    for topology, (n, sF, rmsre) in expected.items():
        row = summary[summary.topology == topology].iloc[0]
        assert row.n == n
        assert row.sF == pytest.approx(sF, rel=1e-12)
        assert row.rmsre == pytest.approx(rmsre, rel=1e-12)
        assert row.status == "approved"
        assert row.packaged_sF == pytest.approx(sF, rel=1e-12)
        assert row.A_flow_m2 == pytest.approx(
            5.94e-4 if topology == "Diamond" else 6.50e-4)

    flagged = quality[~quality.quality_valid].set_index(["topology", "case"])
    assert set(flagged.index) == {
        ("Diamond", "工况10"), ("Diamond", "工况11"),
        ("Gyroid", "工况1"),
    }
    assert flagged.loc[("Gyroid", "工况1"), "exclusion_reason"] == (
        "dp_nonphysical")
    assert flagged.loc[("Diamond", "工况10"), "exclusion_reason"] == (
        "duplicate_row")
    assert flagged.loc[("Diamond", "工况11"), "exclusion_reason"] == (
        "duplicate_row")
    outside = quality[quality.exclusion_reason == "outside_velocity_window"]
    assert dict(outside.groupby("topology").size()) == {
        "Diamond": 7, "Gyroid": 4}


@pytest.mark.skipif(not (_RAW / "7-6-Water-dp.xlsx").exists(),
                    reason="private water+air HX data unavailable")
def test_matching_hx_air_and_water_pair_use_separate_frozen_scales():
    from sjtu_tpmshx.validation.df_refit.fit_experimental_effective import (
        fit_air_hx)

    air, _ = fit_air_hx()
    assert (air.status == "approved").all()
    assert air.rmsre.max() <= 0.10
    assert air.bias.abs().max() <= 0.10
    assert dict(zip(air.topology, air.sF)) == pytest.approx({
        "Diamond": 1.8024228153853061,
        "Gyroid": 2.0119682018983225,
    }, rel=1e-9)

    cfg = _water_air_cfg()
    cfg.validate()
    _, wsf, campaign_w, _ = correction_scale(
        "Diamond", "water", 7.0, 0.6, cfg.fluid_A.u_mps)
    _, asf, campaign_a, _ = correction_scale(
        "Diamond", "air", 7.0, 0.6, cfg.fluid_B.u_mps)
    assert float(np.asarray(wsf)) == pytest.approx(4.892779870412083)
    assert float(np.asarray(asf)) == pytest.approx(1.8024228153853061)
    assert campaign_w == campaign_a == "water-air-hx-7-6"
