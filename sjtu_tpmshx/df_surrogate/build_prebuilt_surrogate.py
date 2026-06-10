"""Regenerate the committed pre-built SurrogateV3 calibrated CSVs.

The training Excel (data/raw_data/试验记录表_整理版.xlsx) is gitignored. This
script — run where the Excel IS available — calibrates the surrogate for each
TPMS and writes the per-geometry (L, t, eps_f, K, c_F) to df_surrogate/_prebuilt/ so
that CI and clones without the raw data can rebuild the RBF and run the
surrogate-dependent test suite. Re-run whenever the surrogate or the training
data changes:

    python -m df_surrogate.build_prebuilt_surrogate
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from df_surrogate.surrogate_v3 import SurrogateV3, XLSX


def main() -> int:
    if not XLSX.exists():
        print(f"[ERROR] training Excel not found: {XLSX}")
        print("Run this where the raw data is available.")
        return 1
    for tpms in ("Diamond", "Gyroid"):
        m = SurrogateV3(tpms=tpms)
        out = m.dump_prebuilt()
        print(f"[prebuilt] {tpms}: {len(m.ref)} geoms -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
