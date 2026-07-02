## 1. 基线与剖析

- [x] 1.1 捕获 golden 2D 基线（`python -u runs/_out/_golden_2d.py runs/_out/golden_2d_pre_simpler.json`），实施后 `--check` 对照
- [x] 1.2 写基准配置构造函数（直接实例化 `SIMPLESolver`：air ideal_gas + massflux inlet + Gyroid DF Shanghai 风格参数、全宽进出口、`wall_refine=False`、40×80 与 80×160 两档网格），先跑 SIMPLE 模式记录外迭代数 + JIT 预热后墙钟 + 各步耗时占比（momentum / PP spsolve / correct / density）→ 实测 PP spsolve 占 83.7%，外迭代触 20 下限（残差 iter 1 即 1e-12）

## 2. SIMPLER 内核与 solve 分支

- [x] 2.1 新增 `_pseudo_u_jit_df` / `_pseudo_v_jit_df`（Numba njit）：复制 `_sweep_u_jit_df`/`_sweep_v_jit_df` 系数块（对流/扩散/DF/壁惩罚/SOU/变 ρμ 插值），去掉 p_src 与欠松弛，单遍 Jacobi 读 u/v 写 û/v̂，填 `d_u`/`d_v`（同公式 `A/aP0`），边界面先整场拷贝携带 BC；两侧头注互指"系数必须逐项同步"
- [x] 2.2 `solve()` 加 `coupling='simple'` 参数 + 校验（非法值 `ValueError`），`'simpler'` 分支按 design D2 组装六步：伪速度 → P 方程（`_assemble_pp_data_jit` 以 û/v̂ 装配 + spsolve + P 直接替换，`simpler_relax_p` 默认 1.0）→ 现有动量扫掠 → 现有 p' → `_correct_jit(alpha_p=0.0)` → 尾部 `_update_density`/残差判据原样
- [x] 2.3 默认路径零 diff 自查：`git diff` 确认 `'simple'` 分支代码未动，golden `--check` PASS（对 1.1 基线）→ GOLDEN-2D PASS (bit-identical)

## 3. 测试

- [x] 3.1 pytest：coupling 参数校验（默认值、显式 'simple'、非法值）
- [x] 3.2 pytest：d 系数 parity — 零流动冻结状态整场 rtol ≤1e-12 + 非零流动单胞手工装配 spot check（spec 场景已同步修订：GS 就地更新使非零场整场比较不适用）
- [x] 3.3 pytest：不可压极限冒烟 — 常密度小网格（16×32）两模式各自收敛，ΔP 相对差 ≤1%、v/P 相对 L2 ≤1e-2、u（近零次级速度）按 ‖v‖ 归一 ≤1e-2、massflux/入口 BC 判据一致（7/7 通过，spec 判据措辞同步修订）
- [x] 3.4 全量 `pytest sjtu_tpmshx/tests/ -q` 通过

## 4. 基准与决策记录

- [x] 4.1 基准脚本 `sjtu_tpmshx/runs/benchmark_simpler_2d.py`：两档网格 × 两模式，输出 (外迭代数, 墙钟, ΔP_A, 场 L2 差) 表 + 一致性 PASS/FAIL 逐项 → β=1.0 无振荡；40×80: 0.46×、80×160: 0.59×，iter ratio 1.00×（两模式均触 20 iter 下限），场一致 PASS
- [x] 4.2 （条件任务）splu 一次分解两次回代 → **跳过（有据）**：条件（PP>40%，实测 83.7%）虽满足，但 iter ratio=1.00× ⇒ 第二次解即使免费 SIMPLER 至多打平，优化无意义。记录于 reports/simpler-coupling-2d/CONCLUSIONS.md
- [x] 4.3 决策记录写入 change → **负结果**：`reports/simpler-coupling-2d/CONCLUSIONS.md` + `benchmark_simple_vs_simpler_2d.csv` + reports/README.md 索引 §4；`coupling='simpler'` docstring 已标 EXPERIMENTAL；不推广 3D
- [x] 4.4 golden 终检（`--check` 对 1.1 基线 PASS）+ 全量 pytest 复跑，PROJECT_MANUAL.md 补 `coupling` 参数一行说明
