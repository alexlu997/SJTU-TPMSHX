# solver-efficiency R1-R4 — 结论（2026-07-02）

openspec change `solver-efficiency-r1-r4`。基准脚本：`sjtu_tpmshx/runs/benchmark_sou_3d.py`（R4）；R1/R3 数据由本报告直接记录。

## R1 — 2D early-exit 移植（大头，✅ 落地）

3D 的 A+B 早退判据（速度稳定性门控 + 平台失速窗口）移植进 2D `SIMPLESolver.solve()`，默认开启，参数与 3D 一致。

| 指标 | 前 | 后 |
|---|---|---|
| golden air-air 管线墙钟 | 47.6 s | **0.29 s（164×）** |
| B 侧（横流）solve 迭代 | 10000 燃尽 ×3，不收敛 | **26 iter 早退 ×3** |
| headline 标量漂移 | — | Q +0.003%、dP_A −0.0008%、dP_B −0.03%（门槛 0.5%）|
| Shanghai 2D aligned RMSRE_dP | 基准 8.35-8.4% | **8.76%**（偏差 0.36pp ≤ 0.5pp 门槛）|
| RMSRE_Q | 2.51% | 2.51%（同一输出）|

golden 2D 已重基线（`runs/_out/golden_2d.json`，有意重基线，pre-R1 基线 `golden_2d_pre_simpler.json` 保留可追溯）。`test_evaluator_frozen_values.py` 的 2D-nonuniform 冻结值同步重基线（Q 1.4e-4 / dP 6.5e-4 rel，plateau 噪声级；uniform 工况在早退触发前已达严格残差 tol，不变；mass 几何 bit-identical）——按该文件既有串行重基线惯例记录。

## R2 — `_update_density` 零分配（✅，bit-identical）

`P_abs`/`rho_new` 持久缓冲 + `out=` 运算。在 R1 之前单独实施并对 pre-change 基线 golden `--check` **PASS (bit-identical)**。ρ 混合保持 rebind（rho_field 可能 alias 调用方数组，不可原地改）。

## R3 — 3D gate 配置阶段剖析（只测，✅）

`validate_shanghai_3d_real --cases 2`（20×10×3 kernel gate runner），cProfile 总 7.3-7.8 s：

| 阶段 | cumtime | 占比 |
|---|---|---|
| **df_surrogate backend 一次性构建**（gamma_df 3.5s + smooth_df 2.4s，内含 pandas excel 读 1.8s） | 4.4 s | **60%** |
| 3D SIMPLE solve() 全部 | 0.2 s | 3.2% |
| 其中 PP 解（AMG/直接） | 0.2 s | 2.4% |
| LTNE 能量 3D | 0.2 s | 2.3% |
| 密度更新 | ~0 | 0.1% |

**决策：无求解器行动**。gate 配置下 3D 求解器不是瓶颈——瓶颈是代理模型一次性初始化（16 case 摊销后无关紧要，且是加载成本非算法成本）。求解器阶段无一 >40%。适用范围声明：小网格 gate 配置；大网格（AMG 激活）占比会不同，届时再测。

## R4 — 3D 动量 SOU opt-in（✅，负结果→保持 opt-in）

minmod SOU 延迟修正（2D N2 telescoping 口径），单一共享 `_sou_axis` helper（9 个方向组合只做 stencil 取值），`use_sou_momentum` 默认 False。

**网格收敛证据**（air ideal-gas、K=2e-8、cF=100、v=15 m/s）：

| 网格 | dP 一阶迎风 | dP SOU | 格式差 |
|---|---|---|---|
| 10×40×10 | 7181.9 Pa | 7182.2 Pa | **0.005%** |
| 20×80×20 | 9096.2 Pa | 9095.3 Pa | **0.010%** |

**结论：不扶正**。TPMS 流动为 DF 源主导（Sp ≫ 对流项），对流格式对 dP 影响 <0.01%，一阶迎风的数值扩散在此物理下不可见。SOU 保持 opt-in（研究用），Shanghai 3D 基线不动。

**flag-off ULP 等价证据**：old vs new（flag off）逐点最大相对差 P 1.4e-16、T 2.5e-14（fastmath 内核加 `use_sou` 分支的重编译指令重排，非物理变化）。严格 bit-identity 需复制 3 份 cell body（~300 行）→ 拒绝（精简约束），golden 3D 有意重基线（`runs/_out/golden_3d.json`）。

## 附带发现

1. **golden 3D 跨进程非确定**：3D stack 输出依赖 `PYTHONHASHSEED`（同一代码两次运行场哈希不同；固定 seed=0 后完全确定）。golden 3D 捕获/校验必须 `PYTHONHASHSEED=0`。2D gate 不受影响。根因（某处 dict/set 迭代序进入运算顺序）未定位，值得另立小事项。
2. 2D 管线提速后，PP spsolve 不再是有效瓶颈（总墙钟 0.29 s）；此前"symbolic-LU 复用/AMG"备忘可降级。
