"""
Diagnostic: ConstDF-v1 in-sample ΔP residual vs Re, three views.

Single figure, 3 rows × 2 cols (rows = view, cols = TPMS):
    row 1 — signed relative residual scatter + binned-median smoother
    row 2 — absolute relative residual scatter + binned-median smoother
    row 3 — per-(L, t) polylines connecting all rows of one geometry

Question: where in (Re, geometry) space does the 2-parameter D-F closure
struggle? Driven by the ConstDF-v1 in-sample residuals, not LOO, so we
isolate structural form-error from generalisation noise.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from .load_data import load_all
from .predict import predict_K_cF_vec
from .train_surrogate import K_S_CELLS

_THIS = Path(__file__).resolve()
_PROJECT = _THIS.parent.parent.parent
OUT_PATH = _PROJECT / "reports" / "figs" / "df_fit" / "residual_vs_re.png"

L_COLORS = {4: "tab:blue", 5: "tab:orange", 6: "tab:green", 8: "tab:red"}
T_MARKERS = {0.3: "o", 0.4: "s", 0.5: "^"}


def _binned_median(x: np.ndarray, y: np.ndarray, n_bins: int = 14
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Robust smoother: median of y inside log10(x) bins.

    Adjacent bins overlap by half a bin-width to make the curve continuous.
    Returns (bin_centres, medians) with bins skipped when n < 3.
    """
    log_x = np.log10(x)
    lo, hi = log_x.min(), log_x.max()
    width = (hi - lo) / n_bins
    centres: list[float] = []
    meds: list[float] = []
    for i in range(2 * n_bins - 1):  # half-bin overlap
        c = lo + (i + 1) * width / 2
        mask = np.abs(log_x - c) <= width / 2
        if mask.sum() < 3:
            continue
        centres.append(10 ** c)
        meds.append(float(np.median(y[mask])))
    return np.array(centres), np.array(meds)


def _residual_arrays(tpms: str, df) -> dict:
    sub = df[df["tpms"] == tpms]
    L = sub["L_mm"].to_numpy(dtype=float)
    t = sub["t_mm"].to_numpy(dtype=float)
    eps_f = sub["eps_f"].to_numpy(dtype=float)
    u = sub["u_mps"].to_numpy(dtype=float)
    Re = sub["Re"].to_numpy(dtype=float)
    dP_obs = sub["dP_Pa"].to_numpy(dtype=float)
    mu = sub["mu"].to_numpy(dtype=float)
    rho = sub["rho"].to_numpy(dtype=float)
    L_ch = K_S_CELLS * L * 1e-3

    K, cF = predict_K_cF_vec(tpms, L, t, eps_f)
    dP_pred = (mu * u / K + rho * cF * u ** 2) * L_ch
    rel = (dP_pred - dP_obs) / dP_obs * 100.0  # signed %
    return {"L": L, "t": t, "Re": Re, "rel": rel}


def _scatter_by_geom(ax, data: dict, signed: bool) -> None:
    L = data["L"]
    t = data["t"]
    Re = data["Re"]
    y = data["rel"] if signed else np.abs(data["rel"])
    for L_val in sorted(set(L)):
        for t_val in sorted(set(t)):
            mask = (L == L_val) & (t == t_val)
            if not mask.any():
                continue
            ax.scatter(
                Re[mask], y[mask],
                c=L_COLORS[int(L_val)],
                marker=T_MARKERS[round(float(t_val), 1)],
                s=24, alpha=0.7, edgecolors="none",
            )


def _polylines_by_geom(ax, data: dict) -> None:
    L = data["L"]
    t = data["t"]
    Re = data["Re"]
    rel = data["rel"]
    for L_val in sorted(set(L)):
        for t_val in sorted(set(t)):
            mask = (L == L_val) & (t == t_val)
            if mask.sum() < 2:
                continue
            order = np.argsort(Re[mask])
            ax.plot(
                Re[mask][order], rel[mask][order],
                color=L_COLORS[int(L_val)],
                marker=T_MARKERS[round(float(t_val), 1)],
                markersize=4, lw=1.0, alpha=0.85,
            )


def _decorate_axis(ax, signed: bool) -> None:
    if signed:
        ax.axhline(0, ls="-", lw=0.7, color="k", alpha=0.7)
        for y in (10, -10):
            ax.axhline(y, ls="--", lw=0.5, color="gray", alpha=0.6)
        for y in (25, -25):
            ax.axhline(y, ls=":", lw=0.5, color="gray", alpha=0.5)
    else:
        ax.axhline(10, ls="--", lw=0.5, color="gray", alpha=0.6)
        ax.axhline(25, ls=":", lw=0.5, color="gray", alpha=0.5)
    ax.set_xscale("log")
    ax.grid(True, ls=":", alpha=0.3)


def main() -> None:
    df = load_all()

    fig, axes = plt.subplots(
        3, 2, figsize=(11, 11), dpi=130,
        sharex=True,
    )

    for col, tpms in enumerate(["Diamond", "Gyroid"]):
        data = _residual_arrays(tpms, df)

        # Row 0: signed scatter + smoother
        ax = axes[0, col]
        _scatter_by_geom(ax, data, signed=True)
        c_x, c_y = _binned_median(data["Re"], data["rel"])
        ax.plot(c_x, c_y, color="k", lw=1.8, label="binned median")
        _decorate_axis(ax, signed=True)
        ax.set_title(f"{tpms}  —  signed residual")

        # Row 1: |residual| scatter + smoother
        ax = axes[1, col]
        _scatter_by_geom(ax, data, signed=False)
        c_x, c_y = _binned_median(data["Re"], np.abs(data["rel"]))
        ax.plot(c_x, c_y, color="k", lw=1.8, label="binned median")
        _decorate_axis(ax, signed=False)
        ax.set_title(f"{tpms}  —  |residual|")
        ax.set_ylim(bottom=0)

        # Row 2: per-(L, t) polylines
        ax = axes[2, col]
        _polylines_by_geom(ax, data)
        _decorate_axis(ax, signed=True)
        ax.set_title(f"{tpms}  —  per-geometry trajectories")
        ax.set_xlabel("Re")

    axes[0, 0].set_ylabel(r"$(\Delta P_{\rm pred}-\Delta P_{\rm obs})/\Delta P_{\rm obs}$  [%]")
    axes[1, 0].set_ylabel(r"$|\Delta P_{\rm rel}|$  [%]")
    axes[2, 0].set_ylabel(r"signed $\Delta P_{\rm rel}$  [%]")

    L_handles = [
        Line2D([], [], marker="o", linestyle="", color=c,
                label=f"L={L_val} mm", markersize=7)
        for L_val, c in L_COLORS.items()
    ]
    t_handles = [
        Line2D([], [], marker=m, linestyle="", color="gray",
                label=f"t={t_val} mm", markersize=7)
        for t_val, m in T_MARKERS.items()
    ]
    smoother_h = [Line2D([], [], color="k", lw=1.8, label="binned median")]
    fig.legend(
        handles=L_handles + t_handles + smoother_h,
        loc="upper center", ncol=8, frameon=False, fontsize=9,
        bbox_to_anchor=(0.5, 1.005),
    )
    fig.suptitle(
        "ConstDF-v1 in-sample ΔP residual vs Re — three diagnostic views",
        fontsize=12, y=1.035,
    )
    fig.tight_layout()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, bbox_inches="tight")
    print(f"Wrote {OUT_PATH.relative_to(_PROJECT)}")


if __name__ == "__main__":
    main()
