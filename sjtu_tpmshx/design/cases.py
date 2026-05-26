"""设计工况 schema 与 Excel 多行多列 loader。"""
from __future__ import annotations
from dataclasses import dataclass
import openpyxl

@dataclass
class DesignCase:
    case: int
    hot_fluid: str; T_in_h: float; P_in_h: float; mdot_h: float
    cold_fluid: str; T_in_c: float; P_in_c: float; mdot_c: float
    Q: float | None            # 换热量 [W] (Q 与 dT 至少一)
    dPlim_h: float; dPlim_c: float   # 分数 (ΔP/P_in)
    dT: float | None = None    # 热侧温降 [K] (与 Q 二选一, 优先)

# 必备基础列; duty 列 (Q_kW / dT_h_K) 至少出现一个
_BASE = ["case","hot_fluid","T_in_h_K","P_in_h_kPa","mdot_h",
         "cold_fluid","T_in_c_K","P_in_c_kPa","mdot_c","dPlim_h","dPlim_c"]

def load_cases(path: str) -> list[DesignCase]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    header = [str(c.value).strip() if c.value is not None else ""
              for c in ws[1]]
    idx = {name: header.index(name) for name in _BASE}
    iQ = header.index("Q_kW") if "Q_kW" in header else None
    idT = header.index("dT_h_K") if "dT_h_K" in header else None
    if iQ is None and idT is None:
        raise ValueError("缺 duty 列: 需 Q_kW 或 dT_h_K 至少一个")
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[idx["case"]] is None:
            continue
        g = lambda n: row[idx[n]]
        Qv = row[iQ] if iQ is not None else None
        dTv = row[idT] if idT is not None else None
        if Qv is None and dTv is None:
            raise ValueError(f"工况 {g('case')}: Q 与 dT 均空")
        out.append(DesignCase(
            case=int(g("case")),
            hot_fluid=str(g("hot_fluid")).strip().lower(),
            T_in_h=float(g("T_in_h_K")), P_in_h=float(g("P_in_h_kPa"))*1e3,
            mdot_h=float(g("mdot_h")),
            cold_fluid=str(g("cold_fluid")).strip().lower(),
            T_in_c=float(g("T_in_c_K")), P_in_c=float(g("P_in_c_kPa"))*1e3,
            mdot_c=float(g("mdot_c")),
            Q=(float(Qv) * 1e3 if Qv is not None else None),
            dPlim_h=float(g("dPlim_h")), dPlim_c=float(g("dPlim_c")),
            dT=(float(dTv) if dTv is not None else None)))
    return out
