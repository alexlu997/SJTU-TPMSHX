# 3D 优化升级 — Scoping 文档

**日期**: 2026-05-08
**状态**: 待用户决定方案后实施
**关联**: option 1 (`validation/verify_pareto_3d.py`) 已完成, 14s/eval 跑通

## 0. 背景

option 1 验证: 2D Pareto row 2 (Q=8564 W/m, dP=10759 Pa) 在 3D extrusion 下 ΔQ=+3%, ΔdP=−19%。说明:

- **2D 优化的 Pareto 排序可信** — 3D 不会改变 trade-off 形状
- **绝对值需要 ~15-20% 修正** — 3D 物理 (z 方向流场, 横向再分布) 不可忽略
- **option 2 的价值**: 直接在 3D 物理上做优化, 消除这 15-20% 的偏差

## 1. 三个子选项

option 2 不是单一方案, 是 3 个子方案。按工作量+质量排:

### 2-fast (推荐): 同 16-D 决策, 3D evaluator

**改什么**:
- 决策空间: 不变 (4×4 + Y-mirror = 16-D)
- L(x, y), t(x, y) 仍 2D B-spline 控制点
- z 方向**保持均匀**拉伸 (不优化 z-DOF)
- 把 `evaluate_design` 替成 3D 版 (复用 verify_pareto_3d.py 的 evaluate_3d 函数)

**工作量**: ~半天 (~1 day max)
- 抽出 verify_pareto_3d.evaluate_3d 成 evaluator_3d.py 公共函数
- optimizer_qnehvi 加 `dim=3` 选项, 路由到 3D evaluator
- 加 cfg key `Lz`
- pytest: 1-2 个 sanity test
- 跑 production: 80 evals × 14s × ~3 outer = ~30-60 min

**收益**:
- 3D 物理直接进 BO 内循环, 优化器看到的 Q/dP 即真值 (无 18% 偏差)
- Pareto 还是 16-D, BO 维度灾难不爆
- 产物可直接进 nTop 拉伸

**局限**:
- 仍假设 z 方向均匀 — graded-z 不可达
- 但 Shanghai z=42 mm 短, z 梯度收益边际

### 2-medium: 加 z-axis 线性 ramp, 24-D

**改什么**:
- 控制点 4×4 × **2 (z-bottom + z-top) = 32 控制 + Y-mirror → 16 唯一 + 8 z-DOF = ~24-D**
- 沿 z 线性插值, L_3D(x,y,z) = L_bot(x,y) · (1-z/Lz) + L_top(x,y) · (z/Lz)
- 同 t

**工作量**: ~2-3 day
- 扩 `field_param.py` 加 z-axis 模式
- 扩 `evaluate_3d` 接 z-graded 输入
- 测试 + 重训 evaluator pytest
- production 64-D 边界, BO 仍稳

**收益**:
- 沿 z 也能优化 (例如 z 方向梯度)
- 24-D vanilla GP 仍 OK

**局限**:
- 制造侧 z 梯度对 Shanghai (z=42 mm) 收益低
- 真适用场景 = z 方向温度有显著梯度 (long HX)

### 2-full: 完全 3D B-spline, 48-96 D + SAASBO

**改什么**:
- 4×4×3 控制网格, ~48 控制点 × 2 = 96-D
- 全 3D bicubic spline
- vanilla GP 不够, 必须 BoTorch SaasFullyBayesianSingleTaskGP

**工作量**: 1-2 周
- 3D B-spline + 控制点采样
- SAASBO 集成 (NUTS HMC ~10-30 min/iter)
- 大量 pytest + V&V
- production 单次 4-12 h

**收益**:
- 真 graded-z 优化, 任意 z 梯度
- 论文 v2 / 后续 milestone 级工作

**局限**:
- 工作量大
- SAASBO 收敛慢, 实际 Pareto 可能不比 2-medium 强多少 (因为 96-D 决策中很多维 redundancy)

## 2. 推荐 — 2-fast

[信心: 高]

**走 2-fast**, 理由:

1. **option 1 验证已证明 2D 优化排序可信** → 我们不缺"找到好 Pareto", 缺"贴 3D 实测的绝对值"
2. **2-fast 直接修这个偏差**, 16-D BO 仍快
3. **z-DOF 在 Shanghai 几何下边际收益低** (z=42 mm, ~6 unit cells, z 梯度空间有限)
4. **代码复用率高** — verify_pareto_3d.evaluate_3d 已写, 抽到公共模块即可

未来 2-medium / 2-full 留作论文 v2 章节。

## 3. 2-fast 实施 plan (若用户选)

1. **抽函数** (~30 min)
   ```
   validation/verify_pareto_3d.evaluate_3d  →  optimization/evaluator_3d.py
   ```

2. **加 dim 路由** (~30 min)
   ```python
   # optimization/optimizer_qnehvi.py _evaluate_batch:
   if cfg.get('dim', 2) == 3:
       Q_neg, dP, _ = evaluate_3d_design(x, cfg)
   else:
       Q_neg, dP, _ = evaluate_design(x, cfg)
   ```

3. **加 cfg key Lz** (~10 min)
   ```python
   DEFAULT_CONFIG['Lz'] = 0.042
   DEFAULT_CONFIG['Nz'] = 16
   ```

4. **pytest 加 2 个 sanity** (~30 min)
   - dim=3 evaluator 在 uniform field 上 Q/dP 物理合理
   - dim=3 与 dim=2 在 Lz→0 极限趋近

5. **跑 production_v2_3d** (~30-90 min wall)
   ```
   python -m runs.run_production_qnehvi_3d
   ```

6. **commit + 文档** (~15 min)

**总工作量**: ~3-4 h coding + 30-90 min 跑

## 4. 用户决策

| 选 | 内容 | 工作量 |
|---|---|---|
| **A** | **走 2-fast** (推荐) | ~1 day |
| B | 跳过 option 2 (维持 2D 优化 + verify_pareto_3d 后处理验证) | 0 |
| C | 走 2-medium | ~3 day |
| D | 走 2-full | 1-2 周 |

直说哪个, 我开干。
