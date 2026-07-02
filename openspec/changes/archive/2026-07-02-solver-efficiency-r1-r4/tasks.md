## 1. R2 — 密度更新零分配（bit-identical，先行）

- [x] 1.1 `_update_density` 持久缓冲（`P_abs`/`rho_new` 用 `out=`），golden 2D `--check` PASS（对 pre-change 基线）→ PASS (bit-identical)

## 2. R1 — 2D early-exit 移植

- [x] 2.1 `solve()` 尾部加 A+B 早退块（照抄 3D 语义：速度稳定门控 + 平台失速窗口；早退路径走 `_enforce_mass_conservation`），属性/默认值与 3D 一致
- [x] 2.2 pytest：早退触发（tol=1e-30 不可达仍收敛 <500 iter）、`lowre_early_exit=False` 回退燃尽、早退态 vs 深跑态一致 ≤5e-3
- [x] 2.3 golden 2D 重捕获（标量漂移 ≤0.03%，门槛 0.5%）；管线墙钟 47.6s → 0.29s（164×），B 侧 10000 燃尽 → 26 iter 早退
- [x] 2.4 `validate_shanghai_aligned.py`：RMSRE_dP 8.76%（基准 8.35-8.4%，偏差 0.36pp ≤ 0.5pp 门槛），RMSRE_Q 2.51% 持平

## 3. R3 — 3D 阶段剖析（只测）

- [x] 3.1 cProfile gate 配置 2 case：求解器仅 3.2%，df_surrogate 一次性构建 60% → **无求解器行动**，表 + 决策入 `reports/solver-efficiency-r1-r4/CONCLUSIONS.md`

## 4. R4 — 3D 动量 SOU opt-in

- [x] 4.1 共享 `_sou_axis` helper + 3 个 cell body 接入（guarded `rhs +=` 保持 flag-off 表达式树；`use_sou_momentum` 默认 False）。发现 fastmath 重编译 ULP 漂移（1e-16~1e-14）+ golden 3D 跨进程非确定（需 PYTHONHASHSEED=0）→ spec 判据修订为 ULP 等价 + 有意重基线（数值证据入报告），golden 3D 以 PYTHONHASHSEED=0 重捕获
- [x] 4.2 pytest：flag off 同进程 bit-identical（array_equal）、`_sou_axis` 与 2D `_sou_corr_u_x`/`_sou_corr_v_y` 逐点对拍（abs ≤1e-15）、flag on 有效且场偏移 ≤10%
- [x] 4.3 网格收敛基准 `runs/benchmark_sou_3d.py`：格式差 0.005%/0.010%（两档）→ DF 源主导，**不扶正**，保持 opt-in

## 5. 收尾

- [x] 5.1 全量 pytest + golden 2D/3D 终检，PROJECT_MANUAL 更新（2D early-exit、3D SOU flag），报告定稿
