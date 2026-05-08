"""
optimization/optimizer_qnehvi.py — qNEHVI Bayesian multi-objective optimizer
for the continuous-field TPMS HX design.

Algorithm choice
----------------
qNEHVI = q-Noisy Expected Hypervolume Improvement (Daulton et al., NeurIPS 2021).
Sample-efficient on 2-objective problems with ~tens of evaluations: typically
50–100 calls to ``evaluate_design`` produce a usable Pareto front, vs the
~5000 needed by NSGA-II under the same population/generation heuristic.
For 16-D the vanilla SingleTaskGP with ARD lengthscales is sufficient — SAAS
prior is reserved for d ≥ 30 where active-dimension identification matters.

Public API
----------
    run_qnehvi(config=None, n_init=32, n_iter=24, q_batch=2,
               seed=42, verbose=True, save_dir=None) -> dict

Returns ``{'X', 'F', 'history_X', 'history_F', 'n_evals', 'save_dir'}``:
  - X : Pareto-optimal decision vectors      shape (P, D)
  - F : Pareto front in minimization form    shape (P, 2) — (-Q, dP)
  - history_X : every evaluated decision     shape (N, D)
  - history_F : every observed objective     shape (N, 2) — (-Q, dP) min-form

CSV checkpoints are written every 5 iterations to ``<save_dir>/pareto_iterNNNN.csv``
plus ``pareto_latest.csv`` for live UI plotting.
"""

from __future__ import annotations

import json
import os
import time
import warnings
from typing import Optional

import numpy as np

from optimization.evaluator import (
    DEFAULT_CONFIG as EVAL_DEFAULT_CONFIG,
    evaluate_design,
)
from solvers.field_param import (
    decision_dim,
    decision_bounds,
)


# ─── Lightweight progress dict for UI consumption ───────────────────


progress: dict = {
    'count': 0,
    'total': 0,
    'best_Q': -float('inf'),
    'phase': 'idle',                    # 'init' | 'optimize' | 'done'
    'cancel_requested': False,
}


def request_cancel() -> None:
    """UI button → set this; the BO loop checks at every iteration boundary."""
    progress['cancel_requested'] = True


def clear_cancel() -> None:
    progress['cancel_requested'] = False


# ─── Pareto utilities ───────────────────────────────────────────────


def _pareto_mask_max(Y: np.ndarray) -> np.ndarray:
    """Boolean mask of non-dominated rows under MAXIMIZATION semantics.

    Y shape: (N, M). A row is non-dominated when no other row weakly dominates
    it on every objective AND strictly dominates on at least one.
    """
    N = Y.shape[0]
    mask = np.ones(N, dtype=bool)
    for i in range(N):
        if not mask[i]:
            continue
        for j in range(N):
            if i == j or not mask[j]:
                continue
            if np.all(Y[j] >= Y[i]) and np.any(Y[j] > Y[i]):
                mask[i] = False
                break
    return mask


def hv_plateau_detected(hv_hist: list, hv_tol: float, hv_window: int) -> bool:
    """Return True iff the last ``hv_window`` relative HV deltas are all
    below ``hv_tol``.

    Used by the BO loop to short-circuit when the Pareto front stops
    advancing materially. Pure-numeric helper exposed at module scope so it
    can be unit-tested without spinning up a full optimization.
    """
    if len(hv_hist) < hv_window + 1:
        return False
    recent = np.asarray(hv_hist[-(hv_window + 1):], dtype=np.float64)
    rel = (recent[1:] - recent[:-1]) / np.maximum(recent[:-1], 1e-12)
    return bool(np.all(rel < hv_tol))


def _save_pareto_csv(path: str, X: np.ndarray, F_min: np.ndarray) -> None:
    """Write CSV: cols = X dims + ['Q', 'dP'] (Q in W/m, dP in Pa, both
    positive)."""
    F_pos = np.column_stack([-F_min[:, 0], F_min[:, 1]])   # (Q, dP)
    header = (','.join(f"x{i}" for i in range(X.shape[1])) +
              ',Q_W_per_m,dP_Pa')
    data = np.hstack([X, F_pos])
    np.savetxt(path, data, delimiter=',', header=header, comments='', fmt='%.6e')


# ─── BO loop ────────────────────────────────────────────────────────


def run_qnehvi(config: Optional[dict] = None,
               n_init: int = 32,
               n_iter: int = 24,
               q_batch: int = 2,
               seed: int = 42,
               verbose: bool = True,
               save_dir: Optional[str] = None,
               progress_cb=None,
               hv_tol: float = 0.01,
               hv_window: int = 3) -> dict:
    """qNEHVI Bayesian multi-objective optimization.

    Parameters
    ----------
    config : dict — overrides over evaluator.DEFAULT_CONFIG (operating point,
        TPMS type, control-point grid, etc.). The keys ``n_ctrl_x``,
        ``n_ctrl_y``, ``symmetric_y``, ``L_bounds``, ``t_bounds`` define the
        decision-vector dimension and bounds.
    n_init : int — Sobol initial samples. Rule of thumb: 2 × decision_dim.
    n_iter : int — BO iterations after init.
    q_batch : int — parallel candidates per iteration (qNEHVI batch size).
    seed : int — random seed for Sobol + BoTorch.
    verbose : bool — print per-iteration HV, best Q, runtime.
    save_dir : str — directory for CSV / config.json. Auto-named if None.
    progress_cb : callable(int, int, dict) — optional UI hook called as
        ``progress_cb(count, total, progress_dict)`` every q_batch evals.
    hv_tol : float — relative HV change threshold for early-stop (default 0.01).
        When the trailing ``hv_window`` iterations all show < hv_tol relative
        gain, the loop exits. Set hv_tol=0 to disable.
    hv_window : int — number of trailing iterations that must all be flat for
        the early-stop to fire (default 3).

    Returns
    -------
    dict with keys:
        'X'         : (P, D) Pareto decision vectors
        'F'         : (P, 2) Pareto in minimization form: (-Q, dP)
        'history_X' : (N, D) all evaluated points
        'history_F' : (N, 2) all observed objectives in min-form
        'n_evals'   : total number of evaluations
        'save_dir'  : path to checkpoint dir
    """
    # Lazy-import torch / botorch so importing this module is cheap when the
    # optimizer isn't actually invoked (e.g. UI startup).
    import torch
    from botorch.models import SingleTaskGP
    from botorch.models.model_list_gp_regression import ModelListGP
    from botorch.models.transforms import Normalize, Standardize
    from botorch.acquisition.multi_objective.monte_carlo import (
        qNoisyExpectedHypervolumeImprovement,
    )
    from botorch.sampling.normal import SobolQMCNormalSampler
    from botorch.optim.optimize import optimize_acqf
    from botorch.utils.multi_objective.box_decompositions.dominated import (
        DominatedPartitioning,
    )
    from botorch.utils.sampling import draw_sobol_samples
    from botorch.fit import fit_gpytorch_mll
    from gpytorch.mlls.exact_marginal_log_likelihood import ExactMarginalLogLikelihood

    cfg = {**EVAL_DEFAULT_CONFIG, **(config or {})}

    # 1. Decision space
    D = decision_dim(cfg['n_ctrl_x'], cfg['n_ctrl_y'], cfg['symmetric_y'])
    lb_np, ub_np = decision_bounds(cfg['n_ctrl_x'], cfg['n_ctrl_y'],
                                    cfg['symmetric_y'],
                                    L_bounds=cfg['L_bounds'],
                                    t_bounds=cfg['t_bounds'])
    bounds = torch.tensor(np.vstack([lb_np, ub_np]), dtype=torch.double)

    if save_dir is None:
        save_dir = f"opt_qnehvi_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(save_dir, exist_ok=True)

    if verbose:
        print(f"[qNEHVI] D = {D} (n_ctrl=({cfg['n_ctrl_x']},{cfg['n_ctrl_y']}), "
              f"symmetric_y={cfg['symmetric_y']})")
        print(f"[qNEHVI] {n_init} Sobol init + {n_iter} iter × q={q_batch} "
              f"= {n_init + n_iter * q_batch} evals total")
        print(f"[qNEHVI] save_dir = {save_dir}")

    with open(os.path.join(save_dir, 'config.json'), 'w') as f:
        json.dump({k: v for k, v in cfg.items()
                   if isinstance(v, (int, float, str, bool, type(None)))},
                  f, indent=2)

    # 2. Reset progress + cancel
    progress['count'] = 0
    progress['total'] = n_init + n_iter * q_batch
    progress['best_Q'] = -float('inf')
    progress['phase']  = 'init'
    progress['cancel_requested'] = False

    dp_cap = float(cfg.get('dp_cap_pa', 1.0e6))

    def _evaluate_batch(X_np: np.ndarray) -> np.ndarray:
        """Evaluate a batch of decision vectors.

        Returns (B, 2) in MAX form (Q, -log10(dP)). The log transform is the
        critical hardening over the v1 evaluator: dP can span 4+ decades
        between converged sweet-spots (~10^3 Pa) and rejected blowups
        (dp_cap ~ 10^6 Pa). On the linear scale that compresses the GP's
        useful resolution onto a sliver of the y-axis; on log10 the entire
        objective range fits in [3, 6] and the ARD lengthscale identifies
        meaningful dP gradients instead of being dominated by outliers.
        """
        F = np.zeros((len(X_np), 2), dtype=np.float64)
        for i, x in enumerate(X_np):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    Q_neg, dP, _mass = evaluate_design(x, cfg)
                Q = -Q_neg
            except Exception as e:
                # Punish failed evals; don't crash the whole loop
                if verbose:
                    print(f"  [eval ERR] x_idx={i}: {e}")
                Q, dP = 1e-6, dp_cap
            # Clamp dP into [1, dp_cap] before log so the transform is
            # always finite and the GP input distribution stays bounded.
            dP_clamped = float(np.clip(dP, 1.0, dp_cap))
            F[i, 0] = Q                                 # maximize Q
            F[i, 1] = -np.log10(dP_clamped)             # maximize -log10(dP)
            progress['count'] += 1
            if Q > progress['best_Q']:
                progress['best_Q'] = float(Q)
            if progress_cb is not None:
                try:
                    progress_cb(progress['count'], progress['total'], progress)
                except Exception:
                    pass
        return F

    # 3. Sobol initial samples
    torch.manual_seed(seed)
    train_X = draw_sobol_samples(bounds=bounds, n=n_init, q=1).squeeze(1)
    train_X_np = train_X.numpy()
    if verbose:
        print(f"[qNEHVI] Evaluating {n_init} Sobol initial points …")
    t_phase = time.perf_counter()
    train_Y_np = _evaluate_batch(train_X_np)
    train_Y = torch.tensor(train_Y_np, dtype=torch.double)
    if verbose:
        print(f"[qNEHVI] init done in {time.perf_counter() - t_phase:.0f}s, "
              f"best Q = {progress['best_Q']:.0f} W/m")

    # 4. Reference point for hypervolume — slightly worse than worst observed
    span = train_Y.max(dim=0).values - train_Y.min(dim=0).values
    ref_point = train_Y.min(dim=0).values - 0.1 * (span.clamp(min=1.0))
    ref_point = ref_point.double()

    progress['phase'] = 'optimize'

    # 5. BO loop
    hv_hist: list = []
    for it in range(n_iter):
        if progress['cancel_requested']:
            if verbose:
                print(f"[qNEHVI] cancel requested → stopping at iter {it+1}")
            break

        t_iter = time.perf_counter()

        # 5a. Fit one GP per objective (independent ARD lengthscales)
        models = []
        for j in range(2):
            m = SingleTaskGP(
                train_X, train_Y[:, j:j+1],
                input_transform=Normalize(d=D, bounds=bounds),
                outcome_transform=Standardize(m=1),
            )
            mll = ExactMarginalLogLikelihood(m.likelihood, m)
            try:
                fit_gpytorch_mll(mll)
            except Exception as e:
                if verbose:
                    print(f"  GP fit warning (obj {j}): {e}")
            models.append(m)
        model = ModelListGP(*models)

        # 5b. Acquisition + candidate selection
        sampler = SobolQMCNormalSampler(sample_shape=torch.Size([128]))
        acq = qNoisyExpectedHypervolumeImprovement(
            model=model,
            ref_point=ref_point,
            X_baseline=train_X,
            sampler=sampler,
            prune_baseline=True,
        )
        candidates, _ = optimize_acqf(
            acq_function=acq,
            bounds=bounds,
            q=q_batch,
            num_restarts=10,
            raw_samples=256,
            options={"batch_limit": 5, "maxiter": 200},
        )

        # 5c. Evaluate candidates
        new_X_np = candidates.detach().numpy()
        new_Y_np = _evaluate_batch(new_X_np)
        new_Y = torch.tensor(new_Y_np, dtype=torch.double)

        train_X = torch.cat([train_X, candidates.detach()], dim=0)
        train_Y = torch.cat([train_Y, new_Y], dim=0)

        # 5d. Hypervolume tracking + checkpoint
        bd = DominatedPartitioning(ref_point=ref_point, Y=train_Y)
        hv = bd.compute_hypervolume().item()
        hv_hist.append(float(hv))
        n_evals = train_X.shape[0]
        if verbose:
            print(f"[qNEHVI] iter {it+1:3d}/{n_iter}  "
                  f"HV={hv:.3e}  best Q={progress['best_Q']:.0f}  "
                  f"n_evals={n_evals}  t={time.perf_counter()-t_iter:.0f}s")

        if (it + 1) % 5 == 0 or it == n_iter - 1:
            _save_current_pareto(train_X, train_Y, save_dir, it + 1)

        # 5e. HV-plateau early stop. Production-quality termination criterion:
        # if the front isn't moving meaningfully, more evals waste budget.
        if hv_tol > 0.0 and hv_plateau_detected(hv_hist, hv_tol, hv_window):
            if verbose:
                print(f"[qNEHVI] HV plateau (rel < {hv_tol:.1%} for "
                      f"{hv_window} iter) → early stop at iter {it+1}/{n_iter}")
            break

    # 6. Extract Pareto and pack output. train_Y stores (Q, -log10(dP)) in
    # MAX form; convert back to (Q_neg, dP) min-form for caller / CSV output.
    Y_np = train_Y.numpy()
    X_np = train_X.numpy()
    mask = _pareto_mask_max(Y_np)
    X_pareto = X_np[mask]
    Y_pareto = Y_np[mask]
    F_min = np.column_stack([
        -Y_pareto[:, 0],
        np.power(10.0, -Y_pareto[:, 1]),
    ])  # (Q_neg, dP)

    F_hist_min = np.column_stack([
        -Y_np[:, 0],
        np.power(10.0, -Y_np[:, 1]),
    ])

    progress['phase'] = 'done'

    if verbose:
        print(f"[qNEHVI] DONE — {len(X_pareto)} Pareto solutions across "
              f"{len(X_np)} total evaluations")
        print(f"  Q range  [{Y_pareto[:, 0].min():.0f}, {Y_pareto[:, 0].max():.0f}] W/m")
        print(f"  dP range [{(-Y_pareto[:, 1]).min():.0f}, {(-Y_pareto[:, 1]).max():.0f}] Pa")

    _save_pareto_csv(os.path.join(save_dir, 'pareto_final.csv'), X_pareto, F_min)
    _save_pareto_csv(os.path.join(save_dir, 'history.csv'), X_np, F_hist_min)

    return {
        'X': X_pareto,
        'F': F_min,
        'history_X': X_np,
        'history_F': F_hist_min,
        'n_evals': int(len(X_np)),
        'save_dir': save_dir,
    }


def _save_current_pareto(train_X: 'torch.Tensor', train_Y: 'torch.Tensor',
                          save_dir: str, step: int) -> None:
    """Write Pareto checkpoint CSV for the current accumulated samples.

    train_Y stores objectives in MAX form (Q, -log10(dP)); we convert to
    (Q_neg, dP) min-form before writing so CSV consumers see real Pa values
    rather than logs.
    """
    Y_np = train_Y.numpy()
    X_np = train_X.numpy()
    mask = _pareto_mask_max(Y_np)
    F_min = np.column_stack([
        -Y_np[mask, 0],
        np.power(10.0, -Y_np[mask, 1]),
    ])
    _save_pareto_csv(os.path.join(save_dir, f'pareto_iter{step:04d}.csv'),
                      X_np[mask], F_min)
    _save_pareto_csv(os.path.join(save_dir, 'pareto_latest.csv'),
                      X_np[mask], F_min)


# ─── Standalone smoke test ──────────────────────────────────────────


if __name__ == '__main__':
    """Smoke run: 16 init + 8 iter × 2 = 32 evals (~10–20 min wall).

    Verifies (relative to the v1 smoke):
      * dp_cap rejects blowups → no 17-MPa Pareto outliers
      * log10-dP transform feeds the GP a bounded objective
      * HV-plateau early-stop short-circuits when the front stops advancing
      * SIMPLE 2000 iter @ tol 1e-4 lets unconverged designs honestly fail
        rather than emit residual-dominated dP estimates
    """
    warnings.filterwarnings('ignore')
    out = run_qnehvi(
        config={'fast_mode': False,
                'max_iter_simple': 2000, 'tol_simple': 1e-4,
                'max_iter_energy': 1500, 'tol_energy': 0.5,
                'dp_cap_pa': 1.0e6, 'reject_unconverged': True},
        n_init=16, n_iter=8, q_batch=2, seed=0,
        verbose=True,
        save_dir=os.path.join('opt_runs', 'smoke_qnehvi_v2'),
        hv_tol=0.01, hv_window=3,
    )
    print(f"\nFinal Pareto: {len(out['X'])} points across {out['n_evals']} evals")
    if len(out['X']) > 0:
        Q  = -out['F'][:, 0]; dP = out['F'][:, 1]
        print(f"  Q range  [{Q.min():.0f}, {Q.max():.0f}] W/m")
        print(f"  dP range [{dP.min():.0f}, {dP.max():.0f}] Pa")
