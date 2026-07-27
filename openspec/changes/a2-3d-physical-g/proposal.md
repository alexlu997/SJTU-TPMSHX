# a2-3d-physical-g — 调查记录：前提证伪，候选关闭

## Why（立项动机，现已证伪）

DECISIONS D3（2026-07-20）调查认为 3D 管线的 massflux 入口捕获发生在"首次真解之后、
出口基准场上"，故 G = 物理值 × P_out_seed/P_in，冻结点亏空 **19.30%**，且被 γ_df
部分吸收——统一物理 G 需 golden 重基准 + Shanghai 重验证 + γ 重锚三件套（候选 A2）。
Alex 2026-07-21 拍板启动调查。

## Verdict（iter 50，三重证据）

**动机性亏空不存在。** 19.30% 与 2D 的 7.38%（iter 41 已证伪）同源自 iter 10 调查的
**1D 种子算术误读**——该推算假设捕获用出口基准密度，与真实捕获时点/数据源不符：

1. **代码链**：`run_stack_3d_stages.py:736` `rho_A = ρ(T_inA, P_inA)`（物理标量）→
   `simple_solver_3d.py:600` 构造平铺 rho_field → `solve()` 入口 hasattr 守卫单次捕获
   （"before any pressure build-up"，:846-857）。3D BO 评估器同构
   （`core/evaluators.py:247,315` 传 `air_density(T_inA, P_inA)`）。
2. **仪器实测**（`upgrade/tools/a2_g_capture_probe.py`，partial-BC 构型抬高 P_inA 至
   Δp/P≈9%）：G_captured/G_physical = **0.995103**。若为出口基准应为 **0.912**。
3. **台账独立记载**：ledger C10（2026-07-12 逐行核对）早已记"mass-flux 目标捕获不棘轮
   ——只捕获一次（prescribed v × 初始 ρ(T_in,P_in)）"，与 D3 背景矛盾；本调查裁决
   C10 读法正确。

## 真实行为（本调查的新发现，量级良性）

捕获发生在**播种线性压剖面**就位之后 ⇒ 捕获密度 = ρ(T_in, **首格中心**播种压)，
比进口**面**基准低半格：偏移 ≈ Δp_seed/(2·N_stream·P_in)。探针实测 **0.49%**
（gauge 切片 16823.9 vs 面 17793.2 Pa，T 切片 = T_in 精确）。此为离散一致性约定
（G 钉在首个 CV 的量纲上），**随网格加密收敛消失**——与被证伪的"出口基准错位"
（不随网格收敛）本质不同。2D 显式 `rho_inlet_ref` 钉的是面基准：两维差一个
半格约定，非物理级分叉；γ_df 拟合时已按各自约定吸收。

## Disposition

- **候选 A2 关闭**：无求解器改动（绊线 4 断言全程绿）；golden/Shanghai/γ 三件套
  全部未动用。
- 半格约定已文档化（本记录 + 绊线契约 docstring 修正 + atlas）；若未来要统一为
  面基准（3D 加显式 `rho_inlet_ref`），其代价=golden 重基准 + 0.5%-收敛级收益，
  **按现证据不立项**——绊线断言继续守门。
- **幸存的相关机会**（非 A2 范围，归候选池）：ledger C8 遗留"种子只是估算，解出
  进口压 ≠ 指定 P_in（case 16：288980 vs 304746），打靶循环可再降一截误差，两维
  同构，未做"——这是真实的、与 G 捕获无关的改进方向。
