from sjtu_tpmshx.validation.cases import validate_d76_3d


def test_d76_validation_entrypoint_keeps_independent_diamond_gate():
    spec = validate_d76_3d.d76_spec()
    assert spec.tpms == "Diamond"
    assert spec.L_cell_mm == 7.0
    assert spec.t_wall_mm == 0.6
    assert validate_d76_3d.D76_N_CASES == 18
    assert validate_d76_3d.D76_EXCLUDE == frozenset({11})
