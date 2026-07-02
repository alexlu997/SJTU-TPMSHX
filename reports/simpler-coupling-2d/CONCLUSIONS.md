# SIMPLER coupling 2D — 基准结论（负结果，2026-07-02）

openspec change `simpler-coupling-2d`。基准脚本 `sjtu_tpmshx/runs/benchmark_simpler_2d.py`，
原始数据 `benchmark_simple_vs_simpler_2d.csv`。

## 问题来源

pysimpler（Tao `Main95.f` 蒸馏版）方腔基准实测 SIMPLER 外迭代 405→121（3.3×↓）。
本实验验证该收益是否可移植到 2D 生产求解器（可压缩 + DF + 质量流量入口 + 稀疏直接解 PP）。

## 结果（Shanghai 风格配置：air ideal-gas、Gyroid、v=15 m/s、tol=1e-6）

| 网格 | SIMPLE iters / wall | SIMPLER iters / wall | 加速 | 场一致性 |
|---|---|---|---|---|
| 40×80 | 20 / 0.15 s | 20 / 0.32 s | **0.46×** | PASS（ΔP 差 1.3e-4） |
| 80×160 | 20 / 1.09 s | 20 / 1.84 s | **0.59×** | PASS（ΔP 差 5.8e-4） |

## 机理（为什么 Tao 的 3.3× 不可移植）

1. **生产 SIMPLE 每外迭代把 p' 方程稀疏直接解到精确** → 质量残差从第 1 迭代就
   在机器精度（实测 1e-12），教科书 SIMPLE 的"p' 欠松弛导致 P 场慢建立"瓶颈不存在。
   Tao 的教学代码用 ADI-TDMA 近似解 p'，SIMPLER 的压力方程才有用武之地。
2. 实际收敛控制是 **α_rho=0.3 的密度松弛**（~15-20 iter 平衡）+ 20 iter 最小下限；
   20→300 iter 的 dP 漂移仅 0.02%（iter-20 已收敛）。两模式都触底 20 iter，
   iter ratio = 1.00×。
3. SIMPLER 每外迭代多一次椭圆解，而 **PP 直接解占 SIMPLE 墙钟 83.7%**（40×80 cProfile）
   → 纯开销，wall 0.5-0.6×。

## 决策

- **`coupling='simpler'` 保留为 experimental**（docstring 已标注），默认 `'simple'` 不变
  （golden 2D bit-identical 已验证）。
- **不做 3D 推广**（3D AMG 下第二次椭圆解更贵，结论只会更糟）。
- **design D4 的 splu 复用优化跳过**：条件（PP>40%）虽满足，但 iter ratio=1.00× 意味着
  即使第二次解免费，SIMPLER 最好也只打平 —— 无意义。
- 顺带发现（未来 2D 提速杠杆，目前无需求）：SIMPLE 墙钟 84% 在 PP spsolve，
  若 2D 速度成为痛点，方向是 PP 解法（symbolic 分解复用 / AMG）而非耦合算法。
- 上游问题（pysimpler 是否接入 / C++ 化）：见 openspec change proposal —— 不接入、
  不 C++ 化；pysimpler 保持独立教学包。
