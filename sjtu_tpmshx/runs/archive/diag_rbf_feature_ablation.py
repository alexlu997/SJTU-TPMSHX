# -*- coding: utf-8 -*-
"""RBF feature-space ablation for the SurrogateV3 D-F surrogate.

Experiment only — production defaults untouched (all variants are opt-in
kwargs on SurrogateV3; default construction stays bit-identical).

Variants:
    V0 baseline   : features (L_mm, t_mm, eps_f), raw scales (production)
    V1 3feat+std  : same features, z-scored. The raw scales are wildly
                    uneven (L_mm spans 4.0, t_mm 0.2, eps_f ~0.1) so the
                    unscaled RBF distance metric is dominated by L_mm.
    V2 (L,t)      : drop eps_f — deterministic function of (L, t), i.e.
                    collinear; training points live on a 2D manifold in
                    the 3D feature space.
    V3 (L,t)+std  : both.

Metrics per variant × TPMS:
    LOO   : mean leave-one-geometry-out MAPE (per-fold refit honors the
            variant config)
    SH    : Shanghai 16-case standalone isothermal RMSRE (Gyroid only —
            Shanghai HX is Gyroid L=7, t=0.6; t is an extrapolation)
    K, cF : prediction at (7.0, 0.6)
"""
import io
import sys
import warnings
from contextlib import redirect_stdout
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from df_surrogate.surrogate_v3 import SurrogateV3, eval_loo, eval_shanghai

VARIANTS = [
    ("V0 baseline", dict()),
    ("V1 3feat+std", dict(standardize=True)),
    ("V2 (L,t)", dict(features=("L_mm", "t_mm"))),
    ("V3 (L,t)+std", dict(features=("L_mm", "t_mm"), standardize=True)),
]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    warnings.filterwarnings("ignore")

    rows = []
    for tpms in ("Gyroid", "Diamond"):
        for name, kw in VARIANTS:
            model = SurrogateV3(tpms=tpms, **kw)
            detail = io.StringIO()
            with redirect_stdout(detail):
                loo = eval_loo(model)
                rmsre = float("nan")
                if tpms == "Gyroid":
                    rmsre, _ = eval_shanghai(model)
            K, cF = model.predict(7.0, 0.6)
            rows.append((tpms, name, loo, rmsre, K, cF))
            print(f"[{tpms:7s}] {name:13s} LOO={loo:6.2f}%  "
                  f"SH={rmsre:6.2f}%  K(7,0.6)={K:.4e}  cF={cF:7.1f}")

    print()
    print(f"{'tpms':>8} {'variant':>13} {'LOO%':>7} {'SH%':>7} "
          f"{'K(7,0.6)':>11} {'cF':>8}")
    print("-" * 60)
    for tpms, name, loo, rmsre, K, cF in rows:
        print(f"{tpms:>8} {name:>13} {loo:7.2f} {rmsre:7.2f} "
              f"{K:11.4e} {cF:8.1f}")


if __name__ == "__main__":
    main()
