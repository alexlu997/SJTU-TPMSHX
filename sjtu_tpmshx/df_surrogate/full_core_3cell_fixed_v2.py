"""Exact-node Darcy--Forchheimer coefficients from three-cell sCO2 CFD."""

from __future__ import annotations

import csv
from math import isfinite
from pathlib import Path


METHOD = "cfd_full_core_3cell_fixed_v2"
TABLE_PATH = Path(__file__).parent / "_prebuilt" / f"{METHOD}.csv"
_TOPOLOGIES = ("Diamond", "Gyroid")
_L_NODES = {4.0, 5.0, 6.0, 7.0, 8.0}
_T_NODES = {0.3, 0.4, 0.5, 0.6}


def _load_table() -> dict[str, dict[tuple[float, float], tuple[float, float]]]:
    tables = {topology: {} for topology in _TOPOLOGIES}
    with TABLE_PATH.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"tp", "L_mm", "t_mm", "K_m2", "cF_fixed_1_m"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("fixed sCO2 CFD coefficient schema mismatch")
        for row in reader:
            topology = row["tp"]
            if topology not in tables:
                raise ValueError(f"unsupported TPMS topology: {topology!r}")
            key = (float(row["L_mm"]), float(row["t_mm"]))
            values = (float(row["K_m2"]), float(row["cF_fixed_1_m"]))
            if key in tables[topology]:
                raise ValueError(f"duplicate fixed sCO2 CFD node: {topology} {key}")
            if key[0] not in _L_NODES or key[1] not in _T_NODES:
                raise ValueError(f"off-grid fixed sCO2 CFD node: {topology} {key}")
            if not all(isfinite(value) and value > 0.0 for value in values):
                raise ValueError(f"invalid fixed sCO2 CFD coefficients: {topology} {key}")
            tables[topology][key] = values

    expected = {(L_mm, t_mm) for L_mm in _L_NODES for t_mm in _T_NODES}
    if any(set(table) != expected for table in tables.values()):
        raise ValueError("fixed sCO2 CFD coefficient grid is incomplete")
    return tables


_TABLE = _load_table()


class FullCore3CellFixedDFV2:
    """Return fixed ``(K, cF)`` at the supported CFD geometry nodes."""

    def __init__(self, tpms: str):
        if tpms not in _TABLE:
            raise ValueError("fixed sCO2 CFD coefficients support Diamond/Gyroid only")
        self.tpms = tpms

    def predict(
        self, L_mm: float, t_mm: float, eps_f: float | None = None
    ) -> tuple[float, float]:
        del eps_f
        try:
            return _TABLE[self.tpms][float(L_mm), float(t_mm)]
        except KeyError as exc:
            raise ValueError(
                "geometry is outside the fixed sCO2 CFD grid: "
                "L=4..8 mm in 1 mm steps, t=0.3..0.6 mm in 0.1 mm steps"
            ) from exc


__all__ = ["FullCore3CellFixedDFV2", "METHOD", "TABLE_PATH"]
