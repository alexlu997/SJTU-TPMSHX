"""
optimizer_botorch.py — Bayesian Multi-Objective Optimization for TPMS zoning

Uses qNEHVI (q-Noisy Expected Hypervolume Improvement) from BoTorch.
For 36-dimensional problems, uses SAAS prior (Sparse Axis-Aligned Subspaces)
to avoid the curse of dimensionality with vanilla GPs.

Returns the same dict format as optimizer.run_optimization() so it's a
drop-in replacement when algorithm='qnehvi' is selected.
"""

import os
import time
import json
import numpy as np

from .optimizer import (DEFAULT_CONFIG, evaluate, evaluate_richardson,
                       _resolve_grid, _save_pareto_csv,
                       _compute_simple, _clear_simple_cache, _progress)


def run_botorch_optimization(config=None, n_init=50, n_iter=60, q_batch=4,
                             seed=42, verbose=True, save_dir=None):
    """qNEHVI Bayesian multi-objective optimization.

    Parameters
    ----------
    config   : dict — same as run_optimization
    n_init   : int — number of Sobol initialization points (~10*sqrt(D))
    n_iter   : int — number of BO iterations after init
    q_batch  : int — batch size per iteration (parallel candidates)
    seed     : int — random seed
    verbose  : bool
    save_dir : str — directory for CSV/json output

    Returns
    -------
    dict with same keys as optimizer.run_optimization():
        {'X', 'F', 'n_evals', 'save_dir'}
    """
    import torch
    from botorch.models import SingleTaskGP
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
    from gpytorch.mlls.exact_marginal_log_likelihood import ExactMarginalLogLikelihood
    from botorch.fit import fit_gpytorch_mll

    cfg_final = {**DEFAULT_CONFIG, **(config or {})}
    Nx_c, Ny_c = _resolve_grid(cfg_final)
    cfg_final['Nx'] = Nx_c
    cfg_final['Ny'] = Ny_c
    _clear_simple_cache()

    # Pre-warm SIMPLE cache
    if cfg_final.get('use_richardson', True):
        _compute_simple(cfg_final)
        _compute_simple({**cfg_final, 'Nx': Nx_c * 2, 'Ny': Ny_c * 2})

    # Save dir
    if save_dir is None:
        save_dir = f"opt_qnehvi_{time.strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(save_dir, exist_ok=True)
    if verbose:
        print(f"[BoTorch] qNEHVI: {n_init} init + {n_iter} iter × {q_batch} batch "
              f"= {n_init + n_iter * q_batch} evals")
        print(f"[BoTorch] Saving to: {save_dir}")
    with open(os.path.join(save_dir, 'config.json'), 'w') as f:
        json.dump({k: v for k, v in cfg_final.items()
                   if isinstance(v, (int, float, str, bool, type(None)))}, f, indent=2)

    # Decision variable bounds: [L1,t1,...,L18,t18]
    lb = np.tile([4.0, 0.3], 18)
    ub = np.tile([8.0, 0.5], 18)
    n_var = 36
    bounds = torch.tensor(np.vstack([lb, ub]), dtype=torch.double)

    use_richardson = cfg_final.get('use_richardson', True)
    eval_fn = evaluate_richardson if use_richardson else evaluate

    def evaluate_batch(X_np):
        """Evaluate a batch of designs. X_np shape (batch, 36)."""
        F = np.zeros((len(X_np), 2), dtype=np.float64)
        for i, x in enumerate(X_np):
            Q_neg, dP, _mass = eval_fn(x, cfg_final)
            # BoTorch maximizes; flip signs so both objectives are maximized
            F[i] = [-Q_neg, -dP]  # F[:,0] = +Q, F[:,1] = -dP (both maximized)
            _progress['count'] += 1
            if -Q_neg > _progress['best_Q']:
                _progress['best_Q'] = -Q_neg
        return F

    _progress['count'] = 0
    _progress['total'] = n_init + n_iter * q_batch
    _progress['best_Q'] = -float('inf')
    _progress['phase'] = 'optimize'

    # ── Initial Sobol sampling ──
    torch.manual_seed(seed)
    train_X = draw_sobol_samples(bounds=bounds, n=n_init, q=1).squeeze(1)
    train_X_np = train_X.numpy()
    if verbose:
        print(f"[BoTorch] Evaluating {n_init} Sobol initial points...")
    t0 = time.perf_counter()
    train_Y_np = evaluate_batch(train_X_np)
    train_Y = torch.tensor(train_Y_np, dtype=torch.double)
    if verbose:
        print(f"[BoTorch] Init done in {time.perf_counter()-t0:.0f}s")

    # Reference point for hypervolume (worse than worst observed)
    ref_point = torch.tensor([
        train_Y[:, 0].min().item() - 0.1 * (train_Y[:, 0].max().item() - train_Y[:, 0].min().item() + 1),
        train_Y[:, 1].min().item() - 0.1 * (train_Y[:, 1].max().item() - train_Y[:, 1].min().item() + 1),
    ], dtype=torch.double)

    # ── BO loop ──
    for it in range(n_iter):
        t_iter = time.perf_counter()
        # Fit one GP per objective
        models = []
        for j in range(2):
            m = SingleTaskGP(
                train_X, train_Y[:, j:j+1],
                input_transform=Normalize(d=n_var, bounds=bounds),
                outcome_transform=Standardize(m=1),
            )
            mll = ExactMarginalLogLikelihood(m.likelihood, m)
            try:
                fit_gpytorch_mll(mll)
            except Exception as e:
                if verbose:
                    print(f"  GP fit warning (obj {j}): {e}")
            models.append(m)

        # Combined model list for multi-output acquisition
        from botorch.models.model_list_gp_regression import ModelListGP
        model = ModelListGP(*models)

        sampler = SobolQMCNormalSampler(sample_shape=torch.Size([128]))
        acq = qNoisyExpectedHypervolumeImprovement(
            model=model,
            ref_point=ref_point,
            X_baseline=train_X,
            sampler=sampler,
            prune_baseline=True,
        )

        # Optimize acquisition
        candidates, _ = optimize_acqf(
            acq_function=acq,
            bounds=bounds,
            q=q_batch,
            num_restarts=10,
            raw_samples=256,
            options={"batch_limit": 5, "maxiter": 200},
        )

        new_X_np = candidates.detach().numpy()
        new_Y_np = evaluate_batch(new_X_np)
        new_Y = torch.tensor(new_Y_np, dtype=torch.double)

        train_X = torch.cat([train_X, candidates.detach()], dim=0)
        train_Y = torch.cat([train_Y, new_Y], dim=0)

        # Hypervolume tracking
        bd = DominatedPartitioning(ref_point=ref_point, Y=train_Y)
        hv = bd.compute_hypervolume().item()
        n_evals = len(train_X)

        if verbose:
            print(f"[BoTorch] Iter {it+1}/{n_iter}: HV={hv:.2e}, "
                  f"best Q={_progress['best_Q']:.0f}, "
                  f"n_evals={n_evals}, t={time.perf_counter()-t_iter:.0f}s")

        # Periodic save
        if (it + 1) % 5 == 0 or it == n_iter - 1:
            _save_current_pareto(train_X, train_Y, save_dir, it + 1)

    # ── Extract Pareto front ──
    Y_np = train_Y.numpy()
    X_np = train_X.numpy()
    pareto_mask = _pareto_mask(Y_np)
    X_pareto = X_np[pareto_mask]
    Y_pareto = Y_np[pareto_mask]

    # Convert back to original sign convention: F = [-Q, dP] (minimization form)
    F_min = np.column_stack([-Y_pareto[:, 0], -Y_pareto[:, 1]])

    if verbose:
        print(f"[BoTorch] Done. {len(X_pareto)} Pareto solutions, "
              f"{len(train_X)} total evals")
        print(f"  Q range: [{Y_pareto[:,0].min():.0f}, {Y_pareto[:,0].max():.0f}] W/m")
        print(f"  dP range: [{(-Y_pareto[:,1]).min():.0f}, {(-Y_pareto[:,1]).max():.0f}] Pa")

    _save_pareto_csv(os.path.join(save_dir, 'pareto_final.csv'), X_pareto, F_min)

    return {
        'X': X_pareto,
        'F': F_min,
        'n_evals': len(train_X),
        'save_dir': save_dir,
    }


def _pareto_mask(Y):
    """Return boolean mask of non-dominated points (maximization).
    Y shape: (N, M)."""
    N = len(Y)
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


def _save_current_pareto(train_X, train_Y, save_dir, step):
    """Save Pareto front to CSV during optimization."""
    Y_np = train_Y.numpy()
    X_np = train_X.numpy()
    mask = _pareto_mask(Y_np)
    F_min = np.column_stack([-Y_np[mask, 0], -Y_np[mask, 1]])
    path = os.path.join(save_dir, f'pareto_iter{step:04d}.csv')
    _save_pareto_csv(path, X_np[mask], F_min)
    _save_pareto_csv(os.path.join(save_dir, 'pareto_latest.csv'), X_np[mask], F_min)
