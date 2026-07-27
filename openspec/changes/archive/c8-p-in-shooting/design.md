# 设计：P_in 打靶（measured-drag 出口锚重种子）

## 0. 不动点与更新式

记 spec 进口绝对压 `P_in`，当前出口锚 `P_ref`，解出的报告口径压降 `Δp`。定义

    realized ≜ P_ref + Δp        （解出的进口绝对压，报告口径）

打靶目标：realized = P_in。更新式用 P² 形式（与既有 1D 种子同一代数）：

    P_out²_new = P_in² − (realized² − P_ref²)
               = P_in² − Δp·(Δp + 2·P_ref)

**为何 P² 而非线性定点** `P_out_new = P_in − Δp`：固定 G 下 1D 可压缩不变量是
`P_in² − P_out² = 2·R·T̄·C·L`（水平无关）；解出的 `realized² − P_ref²` 正是这个
不变量的**实测值**。P² 更新把密度-水平反馈解析吸收——理想 1D 物理下一发命中；
真实 2D/3D 场只剩"离 P² 标度律的偏离"（T 场结构、多维效应，小量），1–2 发进入
0.1% 级。线性定点的收缩率是 1 − P_out/P_in（case 16 ≈ 0.59，5 发才到 0.4%），
且外循环可能先按 dT 收敛退出。

不动点自洽：realized = P_in ⟹ P_out²_new = P_ref²（锚不再动）✓。

## 1. 接线点（每维一处，都在既有外循环内——零额外求解）

### 3D `run_stack_3d_stages._outer_post_3d`
现状：A 侧 `:2749-2755`、B 侧 `:2905-2920` 每外迭代按 1D 闭式 + T_avg 重估
`P_out_sq_new` → `_seed_p_ref`。打靶 = 同位置换数字来源：

```python
if _p_shoot:
    _dp_meas = float(SIMPLESolver3D.extract_dP_face_extrap(sA))
    _pref_old = float(sA.P_ref_abs)
    P_out_sq_new = P_inA**2 - _dp_meas * (_dp_meas + 2.0 * _pref_old)
else:
    P_out_sq_new = P_inA**2 - 2.0*R_AIR*T_avg*C_avg*L_stream   # 现行
sA.P_ref_abs = _seed_p_ref(P_out_sq_new, P_inA, mode=_env_mode, ...)
```

- 走**同一** `_seed_p_ref`：choke 门语义随 `envelope_mode`（raise/warn/off）不变。
  实测阻力说 Δp ≥ P_in ⇒ 谱内确无定常解，raise 正当。
- 初始种子（`:806/:896`，预解 choke 检查）不动——打靶从第一次 post 起接管。
- post(0) 用的是冷解 Δp（暖 T 未进场）——后续 post 用暖解逐发修正，收敛性
  自愈；dT 门要求 ≥2 步才可能退出，故至少打一发。
- 报告口径 = `extract_dP_face_extrap`（管线 headline dP 同源），realized 与
  报告的 dP 自洽。

### 2D `stages_2d._run_simple` + `solve_2d._step_2d`
2D 每外迭代**重建**求解器（rho_inlet_ref 同理），上一轮 Δp 须由调用方传入：

- `_run_simple(..., p_shoot_prev=None)`：`(P_ref_prev, dP_prev)` 元组。
  ideal_gas 且 knob ON 且元组非 None → 在既有 graded 重种子**之后**覆盖：
  `s.P_ref_abs = sqrt(max(P_in² − dP·(dP+2·P_ref_prev), 1e4))`。
  clip 姿态与既有 2D 种子一致（O1：无 raise，地板 1e4——不在本变更里加守卫）。
- `_step_2d`：`simpA/simpB` nonlocal（上一迭代实例），传
  `p_shoot_prev=(P_ref_abs, Δp_2D口径)`；首迭代传 None。
- 2D Δp 口径 = `_pipe_weighted(P[:,0], inlet_frac) − _pipe_weighted(P[:,-1],
  outlet_frac)`（`_compute_pressure_2d` 报告同式）。`_pipe_weighted` 从嵌套函数
  提为模块级复用（verbatim，golden 中性）。

## 2. 旋钮与默认

`p_in_shooting`：cfg 显式 > env `TPMSHX_P_IN_SHOOT`('1'=on) > 默认。
本提交默认 **OFF**（golden 双维逐位同）；定价实测后另行 `!` 提交翻 ON（§5 流程）。
3D 读 cfg dict（`cfg.get('p_in_shooting', env)`）；2D 在 `_run_simple` 同式读
（closure 里有 cfg）。

## 3. 诊断（knob 无关，恒发射）

结果字典（两维）新增可压缩侧：

    P_in_realized_A/B   = P_ref_abs_final + Δp_final     [Pa 绝对]
    P_in_shoot_resid_A/B = (realized − P_in_spec)/P_in_spec

OFF 模式的既有偏差从此可见（定价证据直接读它）。golden 脚本只取白名单标量，
新键不入哈希——OFF 位同不受影响。

## 4. 明确不做

- evaluator（2D/3D BO）：不打靶——O2 约定 evaluator 只出排名；分歧记档不加码。
- kernel-direct 验证 runner：自播种 1D，路径独立（O2），不动。
- 2D choke 守卫：仍缺（O1 开放项，独立变更）。
- 外循环收敛门不加压力残差项：P² 更新 1–2 发命中，dT 门的既有迭代数
  足够；`P_in_shoot_resid` 诊断兜底暴露任何不足（若定价发现例外再议）。

## 5. 失效模式清点

| 模式 | 处置 |
|---|---|
| 实测阻力 ⇒ P_out² ≤ 0（真 choke @ spec 进口压） | 3D 走 `_seed_p_ref` 门（raise/warn/off）；2D clip 1e4 地板（现状姿态） |
| 冷解 Δp 偏差把首发打歪 | 后续发次自愈（P² 收缩）；dT 门保证 ≥1 发 |
| 外循环按 dT 早退、打靶未收 | `P_in_shoot_resid` 诊断可见；定价阶段核查全部 16 工况 |
| 不可压缩侧误入 | 结构性排除：3D `_mA/_mB.compressible` 门、2D `fluid_type=='ideal_gas'` 门（与既有种子同门） |

## 6. 定价实测（2026-07-22，iter 57）——默认翻转被证据否决

**执行**：`TPMSHX_P_IN_SHOOT=1` 跑上海双维验证器 + golden 双维捕获（日志
job tmp/c8_on_{3d,2d,g3d,g2d}.log；OFF 逐工况 = tracked shanghai_3d_baseline.csv）。

**3D（20×10×3，16 工况）**：case 1–11 完成、**case 12 起 in-model choke**
（P_inA=246566，打靶重种子 P_out²=−1.39e9，Δp_exp/P_in=0.52）。err_dP
OFF→ON：case 5 +1.3→+3.6、6 +0.2→+4.0、7 −0.5→+4.2、8 −1.4→+4.1、
9 −2.0→+4.6、10 −2.1→+5.8、11 −1.5→+8.0——**单调随 Δp 放大 +2~9.4pp**；
同 11 工况 RMSRE_dP ≈5.5%→≈6.7%（OFF 全 16 = 4.88%）。Q 几乎不动。

**2D（16 工况）**：RMSRE_dP **8.62%→10.73%**（bias −9.50%），Q 2.49% 持平；
case 16 dP ON=−7.1%（OFF 参照：C8 台账 2026-07-12 实测 +6.8%）。方向与 3D
相反、机理同根（2D 的 1D 种子**过**估阻力→实现进口压偏低；3D 该网格下
**欠**估→偏高）。

**golden ON**：3D air_air 在 15³ 亦 choke（B 侧 P_inB=101325、dP_B/P=53% 的
工况点 in-model 无定常解，12³ 同）；2D 可跑，dP_A −1.36%（air_air）/
−2.50%（water_b 空气 A），Q ≤0.5%。

**机理裁定（证伪级结论）**：打靶本身全对（测试证实实现进口压钉到 spec）；
坏的是**闭合-标定纠缠**——γ_df 是穿过"压力水平随 1D 种子误差漂移"的旧口径
标到实验 Δp 上的，那个约定性偏置被锚点吸收；打靶把补偿拆掉，闭合的真误差
（高 Δp 角落过预测）裸露并单调放大，近谱工况直接翻出谱外。与 A2（G 口径）
同构：**约定修正必须与 γ 重锚同波做**——正是 ROADMAP 候选 D 预告的耦合
（"D3 若改 G 口径则 γ 锚点移动"，C8 同理）。

**处置**：默认保持 OFF（两维），能力/诊断/测试全部保留；翻转的前置 =
候选 D 的 γ_df 重锚战役（重启触发写入 DECISIONS D5）。golden air-B 工况点
"隐蔽越谱"（Δp/P=53–55%）作为独立事实一并交 D5。
