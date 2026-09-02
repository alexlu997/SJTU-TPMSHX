"""D-F surrogate backend registry (B2 2.2, 2026-06-12).

Replaces the inline if/else dispatch in ``predict.py`` with explicit
backend classes behind one interface. Each backend wraps its model and
owns its own semantics — notably the K clamp:

  * ``rbf``      — SurrogateV3. Keeps the historical ``K_MIN = 1e-8``
                   clamp INSIDE this adapter (the validated Shanghai RBF
                   numbers were measured with it). Vectorised path is the
                   native batched RBF evaluation.
  * ``gamma_df`` — GammaDF (production default since v1.4.0). Clamp-free
                   by design (the clamp floored true K ≈ 1e-9 of L4/L5
                   geometries and was the LOO error driver). Vectorised
                   path is a per-unique-(L, t) scalar cache.

REGISTRATION CONTRACT — read before adding a backend or switching the
default: a new backend (or default switch) must be validated against the
Shanghai 3D Nz=3 gate (validation/cases/validate_shanghai_3d_real.py), with the
result recorded in the PR.
Training-domain metrics are NOT sufficient — precedent: plhub_gp won
every training-domain metric (LOO 32.1→11.8%) and scored dP RMSRE 62.79%
on the Shanghai end-to-end gate (2026-06-10).

Diagnostics access: backends pass unknown attributes through to the
wrapped model (``backend._rbf_K``, ``backend.K_min``, ``.summary()`` …),
so existing introspection call sites keep working unchanged.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

_REGISTRY: dict[str, type] = {}
_CACHE: dict[tuple[str, str], 'DFBackend'] = {}


def register(name: str):
    """Class decorator: register a DFBackend under ``name``."""
    def deco(cls):
        cls.name = name
        _REGISTRY[name] = cls
        return cls
    return deco


def available_methods() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def get_backend(tpms_type: str, method: str) -> 'DFBackend':
    """Cached backend instance for (tpms_type, method)."""
    key = (tpms_type, method)
    if key not in _CACHE:
        try:
            cls = _REGISTRY[method]
        except KeyError:
            raise ValueError(f"unknown DF method {method!r}; "
                             f"valid: {available_methods()}")
        _CACHE[key] = cls(tpms_type)
    return _CACHE[key]


class DFBackend(ABC):
    """One D-F coefficient backend: (L_mm, t_mm, eps_f) → (K [m²], c_F [1/m])."""
    name: str = ''

    def __init__(self, tpms_type: str):
        self.tpms = tpms_type
        self._model = self._build(tpms_type)

    @abstractmethod
    def _build(self, tpms_type: str):
        """Construct and return the wrapped model."""

    def predict(self, L_mm: float, t_mm: float,
                eps_f: float) -> tuple[float, float]:
        return self._model.predict(L_mm, t_mm, eps_f)

    def predict_vec(self, L_flat: np.ndarray, t_flat: np.ndarray,
                    e_flat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Flat-array prediction; generic fallback is a per-element loop.
        Backends override with their native vectorisation."""
        K = np.empty(L_flat.size)
        cF = np.empty(L_flat.size)
        for i in range(L_flat.size):
            K[i], cF[i] = self.predict(float(L_flat[i]), float(t_flat[i]),
                                       float(e_flat[i]))
        return K, cF

    def __getattr__(self, item):
        # Diagnostics passthrough (only reached when normal lookup fails).
        return getattr(self._model, item)


@register('gamma_df')
class GammaBackend(DFBackend):
    def _build(self, tpms_type):
        from .gamma_df import GammaDF
        return GammaDF(tpms=tpms_type)

    def predict_vec(self, L_flat, t_flat, e_flat):
        # Verbatim semantics of the retired predict_K_cF_vec gamma branch:
        # evaluated per unique (L, t) pair with a local cache — exact and
        # fast for zoned/uniform designs (eps_f derived internally).
        K = np.empty(L_flat.size)
        cF = np.empty(L_flat.size)
        pair_cache: dict[tuple[float, float], tuple[float, float]] = {}
        for i in range(L_flat.size):
            key = (L_flat[i], t_flat[i])
            if key not in pair_cache:
                pair_cache[key] = self._model.predict(key[0], key[1])
            K[i], cF[i] = pair_cache[key]
        return K, cF


@register('rbf')
class RBFBackend(DFBackend):
    def _build(self, tpms_type):
        from .surrogate_v3 import SurrogateV3
        return SurrogateV3(tpms=tpms_type)

    def predict_vec(self, L_flat, t_flat, e_flat):
        # Verbatim semantics of the retired predict_K_cF_vec rbf branch:
        # native batched RBF eval (~50x vs per-cell loop, audit H2) with
        # the historical K clamp — backend-internal, NOT a shared-layer
        # floor (gamma_df is clamp-free by design).
        X = np.column_stack([L_flat, t_flat, e_flat])
        log_K = self._model._rbf_K(X)
        log_cF = self._model._rbf_cF(X)
        K = np.maximum(10.0 ** log_K, self._model.K_min)
        cF = 10.0 ** log_cF
        return K, cF
