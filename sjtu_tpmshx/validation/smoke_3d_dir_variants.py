"""smoke_3d_dir_variants.py — verify run_calculation_3d under all dir_A values.

For uniform-flow Shanghai-like setup, swapping streamwise axis (dir 0/1 vs 2/3)
or sign (forward vs reverse) should give physically identical Q + dP after
domain remap. Here we just check no crash + same Q/dP magnitude across dirs
(modulo numerical rounding).
"""
from __future__ import annotations
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# No GUI needed for the inner runner
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    from main import Main_Menu
    w = Main_Menu()

    # Tiny grid for quick per-direction sweep
    w.le_Nx.setText('14'); w.le_Ny.setText('14'); w.le_Nz.setText('3')
    w.le_L.setText('0.10'); w.le_H.setText('0.10'); w.le_Lz.setText('0.02')
    w.combo_dim.setCurrentIndex(1)

    from runs.run_calculation_3d import run_calculation_3d_inner

    # Patch _fluid_config to feed each dir
    original = w._fluid_config
    results = {}
    for d in (0, 1, 2, 3):
        # Centre + width for cross-stream extent (full face)
        cross_dim = 0.10
        w._fluid_config = lambda which='A', _d=d, _c=cross_dim: dict(
            dir=_d,
            in_ctr=_c / 2, in_w=_c,
            out_ctr=_c / 2, out_w=_c,
        )
        try:
            run_calculation_3d_inner(w)
            res = w._result_3d
            results[d] = (res['Q'], res['dP'])
            print(f"  dir={d}: Q={res['Q']:.2f} W   dP={res['dP']:.0f} Pa")
        except Exception as e:
            print(f"  dir={d}: FAIL — {e}")
            results[d] = None
            import traceback; traceback.print_exc()
    w._fluid_config = original

    # Sanity: dir 0 vs 1 (same streamwise axis, opposite sign) should match in
    # magnitude. dir 2 vs 3 should also match. dir 0 vs 2 may differ slightly
    # because L≠H breaks symmetry; with L=H here they should match.
    if all(v is not None for v in results.values()):
        Qs = [results[d][0] for d in (0, 1, 2, 3)]
        dPs = [results[d][1] for d in (0, 1, 2, 3)]
        rel_Q = (max(Qs) - min(Qs)) / max(max(Qs), 1e-9)
        rel_dP = (max(dPs) - min(dPs)) / max(max(dPs), 1e-9)
        print(f"\nVariation across dirs: rel_Q={rel_Q:.3%}  rel_dP={rel_dP:.3%}")
        assert rel_Q < 0.05, f"Q variance {rel_Q:.3%} > 5%"
        assert rel_dP < 0.05, f"dP variance {rel_dP:.3%} > 5%"
        print("\nSMOKE PASS — all 4 dir_A values converge to same Q/dP.")
        return 0
    print("\nSMOKE FAIL — at least one direction failed.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
