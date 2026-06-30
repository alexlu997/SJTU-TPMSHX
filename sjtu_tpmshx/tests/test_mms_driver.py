"""B2 2.5 — shared MMS grid-sweep loop semantics."""
import importlib


def test_run_grid_sequence_order_and_rows():
    from validation.harness._mms_driver import run_grid_sequence
    calls = []
    rows = run_grid_sequence(
        [4, 8],
        lambda g: {'val': g * 10},
        lambda g, r, dt: {'N': g, 'val': r['val'], 'dt_nonneg': dt >= 0.0},
        on_grid=lambda g, r, row, dt: calls.append((g, row['val'])))
    assert [r['N'] for r in rows] == [4, 8]
    assert [r['val'] for r in rows] == [40, 80]
    assert all(r['dt_nonneg'] for r in rows)
    assert calls == [(4, 40), (8, 80)]   # progress fired per grid, in order


def test_sweep_scripts_import():
    for mod in ('validation.cases.mms_phase_a3_h_refine',
                'validation.cases.mms_phase_a4_boundary',
                'validation.cases.mms_phase_b4_order'):
        importlib.import_module(mod)
