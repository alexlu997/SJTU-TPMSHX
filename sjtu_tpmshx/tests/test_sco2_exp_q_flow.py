"""Mass-flow mapping used by the sCO2 experimental-Q validation."""

import numpy as np
import pytest

from sjtu_tpmshx.df_surrogate.predict import SCO2_DF_METHOD
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver
from sjtu_tpmshx.validation.cases.validate_sco2_exp_q import (
    GROSS_FACE_M2,
    _flow_velocity,
    _solver_geometry,
)


@pytest.mark.parametrize("topology", ["Diamond", "Gyroid"])
def test_solver_velocity_reconstructs_measured_mass_flow(topology):
    mdot = 0.05
    rho_in = 125.0
    geo = _solver_geometry(topology)
    u_in = _flow_velocity(mdot, rho_in, geo["void_area_m2"])

    assert geo["void_area_m2"] == pytest.approx(
        0.5 * geo["epsilon"] * GROSS_FACE_M2)
    assert rho_in * u_in * geo["void_area_m2"] == pytest.approx(
        mdot, rel=1e-12)


def test_explicit_reference_keeps_variable_density_inlet_mass_flux():
    rho = np.full((4, 5), 100.0)
    rho[:, 0] = 110.0
    solver = SIMPLESolver(
        W=0.04, H=0.05, Nx=4, Ny=5,
        tpms_type="Gyroid", L_cell_mm=7.0, t_mm=0.6,
        eps=0.7, r_h=1.0e-3, rho=rho, mu=2.0e-5, T_in=400.0,
        inlet_lo=0.0, inlet_hi=0.04, v_inlet=0.5,
        wall_refine=False, fluid_type="incompressible",
        rho_inlet_ref=125.0, df_method=SCO2_DF_METHOD,
    )
    solver.solve(max_iter=1, tol=0.0, verbose=False)

    assert np.allclose(solver.rho_field[:, 0] * solver.v[:, 0], 62.5)


# Synthetic full selections: no workbook or production pipeline is run.
def _q_results(diamond=0.20, gyroid=0.05):
    import pandas as pd

    rows = [dict(dimension=dim, topology=topo, case=case,
                 Q_ref_W=100.0, Q_solver_W=100.0 * (1.0 + error),
                 Q_error_rel=0.0, numerical_ok=True, df_mode="cfd_smooth")
            for dim in ("2d", "3d")
            for topo, error in (("Diamond", diamond), ("Gyroid", gyroid))
            for case in (1, 2)]
    result = pd.DataFrame(rows)
    result.attrs["expected_cases"] = {"Diamond": [1, 2], "Gyroid": [1, 2]}
    return result


@pytest.mark.parametrize("diamond,gyroid,passed", [
    (0.20, 0.05, True), (0.20 - 1e-8, 0.05 - 1e-8, True),
    (0.20 + 1e-8, 0.0, False), (0.0, 0.05 + 1e-8, False),
    (-0.20, -0.05, True), (-0.20 - 1e-8, 0.0, False),
])
def test_q_limits_use_actual_q_per_group(diamond, gyroid, passed):
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(diamond, gyroid)
    # Deliberately inconsistent error column must never manufacture a pass.
    assert runner._accept_q(result, result.attrs["expected_cases"],
                            ["2d", "3d"]) is passed


@pytest.mark.parametrize("failure", [
    "empty", "missing_group", "missing_case", "duplicate", "unexpected",
    "nan", "inf", "zero_ref", "negative_ref", "numerical", "null_numerical",
    "empty_expected", "singleton", "one_bad_dimension",
])
def test_q_acceptance_rejects_incomplete_or_invalid_results(failure):
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(0.0, 0.0)
    expected = result.attrs["expected_cases"]
    if failure == "empty":
        result = pd.DataFrame()
    elif failure == "missing_group":
        result = result.iloc[2:]
    elif failure == "missing_case":
        result = result.iloc[1:]
    elif failure == "duplicate":
        result.loc[1, "case"] = 1
    elif failure == "unexpected":
        result.loc[1, "case"] = 99
    elif failure in ("nan", "inf"):
        result.loc[0, "Q_solver_W"] = float(failure)
    elif failure in ("zero_ref", "negative_ref"):
        result.loc[0, "Q_ref_W"] = 0.0 if failure == "zero_ref" else -100.0
    elif failure == "numerical":
        result.loc[0, "numerical_ok"] = False
    elif failure == "null_numerical":
        result["numerical_ok"] = result["numerical_ok"].astype("boolean")
        result.loc[0, "numerical_ok"] = pd.NA
    elif failure == "empty_expected":
        expected = {"Diamond": [], "Gyroid": [1, 2]}
    elif failure == "singleton":
        expected = {"Diamond": [1], "Gyroid": [1]}
        result = result[result.case == 1]
    else:
        result.loc[4:5, "Q_solver_W"] = 130.0  # 3D Diamond alone exceeds 20%.
    assert not runner._accept_q(result, expected, ["2d", "3d"])


def test_fixed_selection_and_run_manifest(monkeypatch):
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    df = pd.DataFrame([
        dict(case=case, side=side, ok_done=True, ok_hb=True,
             ok_dp=False, ok_dT=False, Tin_C=100.0, Tout_C=110.0,
             Pin_MPa=9.0, Pout_MPa=8.0, mdot=0.05)
        for case in range(1, 6) for side in ("hot", "cold")])
    df.loc[df.case == 3, "ok_hb"] = False
    df.loc[(df.case == 4) & (df.side == "cold"), "Pin_MPa"] = 17.0
    df.loc[df.case == 5, "ok_done"] = False
    assert runner._valid_case_numbers(df) == [1, 2]
    monkeypatch.setattr(runner, "load_exp", lambda topology: df)
    monkeypatch.setattr(runner, "_print_geometry", lambda *args: None)
    monkeypatch.setattr(runner, "_print_summary", lambda *args: None)
    calls = []

    def fake_case(topology, case, dimension, frame):
        calls.append((topology, case, dimension))
        return dict(topology=topology, case=case, dimension=dimension,
                    flow_err_hot_rel=0., flow_err_cold_rel=0., Q_solver_W=100.,
                    Q_hot_exp_W=100., Q_cold_exp_W=100., Q_error_rel=0.,
                    enthalpy_imbalance_rel=0., numerical_ok=False, df_mode="cfd_smooth")

    monkeypatch.setattr(runner, "_run_case", fake_case)
    result = runner.run(["Diamond", "Gyroid"], ["2d", "3d"],
                        case=None, all_valid=True)
    assert len(calls) == len(result) == 8  # Failed cases remain in the result.
    assert result.attrs["expected_cases"] == {"Diamond": [1, 2], "Gyroid": [1, 2]}
    assert result.attrs["ranges"]["Diamond"]["Pin_MPa"] == [9., 9.]


@pytest.mark.parametrize("args", [
    ["--accept-q"], ["--accept-q", "--case", "1", "--topology", "Diamond"],
    ["--accept-q", "--all-valid", "--case", "1", "--topology", "Diamond"],
])
def test_q_cli_requires_full_selection_before_loading(monkeypatch, args):
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    monkeypatch.setattr("sys.argv", ["validate_sco2_exp_q", *args])
    monkeypatch.setattr(runner, "load_exp", lambda *args: pytest.fail("loaded data"))
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("accept,over_limit,exit_code", [
    (False, True, 0), (True, True, 1), (True, False, 0),
])
def test_q_cli_verdict_and_legacy_csv(monkeypatch, tmp_path, capsys,
                                     accept, over_limit, exit_code):
    import json
    import pandas as pd
    from sjtu_tpmshx.validation.cases import validate_sco2_exp_q as runner

    result = _q_results(0.21 if over_limit else 0.20, 0.05).iloc[:2].copy()
    result.attrs["expected_cases"] = {"Diamond": [1, 2]}
    output = tmp_path / "q.csv"
    args = ["runner", "--topology", "Diamond", "--dimension", "2d",
            "--csv", str(output)]
    if accept:
        args += ["--all-valid", "--accept-q"]
    monkeypatch.setattr("sys.argv", args)

    def fake_run(topologies, dimensions, *, case, all_valid):
        assert topologies == ["Diamond"] and dimensions == ["2d"]
        assert case is None and all_valid is accept
        return result

    monkeypatch.setattr(runner, "run", fake_run)
    assert runner.main() == exit_code
    assert len(pd.read_csv(output)) == 2  # No comment-header format change.
    metadata = json.loads(output.with_suffix(".csv.meta.json").read_text())
    assert metadata["expected_cases"] == {"Diamond": [1, 2]}
    assert metadata["dimensions"] == ["2d"]
    assert metadata["df_modes"] == ["cfd_smooth"]
    assert metadata["actual_data_revision"] == "unverified"
    assert metadata["exit_ok"] is (exit_code == 0)
    assert bool(metadata["commit"])
    if accept:
        assert "not G1/G2 or full-core energy acceptance" in capsys.readouterr().out
