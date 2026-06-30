# 703 — sCO2 PCHE / 预冷器评估（D-7-6 晶胞）

项目合作交付：合作方 **703** 的 sCO2 印刷电路板换热器（PCHE）/ 预冷器评估。几何采用 **D-7-6**（Diamond，L=7.0 mm / t=0.6 mm）TPMS 晶胞及其对应参数。

这些是**驱动脚本**——它们 `import` 主代码包 `sjtu_tpmshx/`（求解器 / 关联式 / 压降代理）来跑评估，本身不含内核代码。实验数据存放在仓库根的 `data/raw_data/D-7-6-sCO2/`。

## 脚本一览

| 脚本 | 用途 |
|---|---|
| `size_sco2_703.py` | Method-A 定尺：给定工况反推 PCHE 尺寸（DEVICES / design_device）。 |
| `validate_sco2_703_3d.py` | METHOD iii：3D 场跑（sCO2 双侧全泛化）。逆流；报 dP + 热侧焓 duty。⚠ 3D 有 B 侧守恒泄漏，coupled duty 不可信——用下面的 2D coupled。 |
| `validate_sco2_703_coupled.py` | 2D 双活耦合求解（imbalance −1.9%）——可信的耦合 duty。 |
| `validate_sco2_703_field.py` | 场跑（复用 `size_sco2_703` 的定尺结果）。 |
| `validate_sco2_precooler_phasec.py` | 预冷器 Phase-C 评估。 |
| `precooler_nu_sensitivity.py` | 预冷器 Nu 关联式敏感性扫描。 |
| `validate_sco2_d76.py` | **Gate A**：sCO2 Nu 闭合 vs D-7-6 实验（集总双-Nu ε-NTU）。Gate：max\|Q 误差\|<15%。 |
| `validate_sco2_d76_2d.py` | D-7-6 2D 场验证。 |
| `validate_sco2_d76_dP_holdout.py` | D-7-6 ΔP holdout（导入 `validate_sco2_d76_2d` 的 `_run_case` / `XLSX` / `GOLD`）。 |

## 运行（从仓库根目录）

```bash
python -u projects/703-sCO2-D76/validate_sco2_d76.py            # 快速 Gate A
python -u projects/703-sCO2-D76/validate_sco2_703_coupled.py    # 可信耦合 duty
TPMSHX_ALLOW_EXTRAP=1 python -u projects/703-sCO2-D76/validate_sco2_703_3d.py
```

> 脚本通过 `Path(__file__).resolve().parents[2] / "sjtu_tpmshx"` 把包挂上 `sys.path`，所以从仓库根目录或本文件夹运行都能解析 `from solvers ...`。`validate_sco2_d76_*` 读取仓库根 `data/raw_data/D-7-6-sCO2/`（深度不变，搬动后无需改路径）。
