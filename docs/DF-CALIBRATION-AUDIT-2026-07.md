# D-F 标定溯源审计（候选 D · D-0，2026-07-22，iter 59）

升级循环产出。目的：候选 D（D-F 系数获取方法重锚）开工前，把现行 γ 锚定的完整
出身、数据资产、口径纠缠钉到 file:line，并记录 Alex 两次拍板后的执行边界。

## 1. 边界（Alex 2026-07-22 两次拍板）

1. 全串行批到位；关键决策点（换默认、γ_f 选侧、golden air-B 换点）停下问。
2. CFD 拟合 (K, cF) 光滑基，试件/实验数据标定 γ；**上海 16 例退出标定、转纯盲考卷**。
3. **sCO2 先行**（二次拍板）：用 subst.v2 修正关联式先修 CFD f → 更正确的 Δp →
   提 (K, cF)；水/空气排后，用同一套工具链。
4. UQ 是交付物（γ 后验 + Δp 预测带）。

## 2. 数据资产地图（本轮逐一实测核过）

| 资产 | 内容 | 候选 D 角色 |
|---|---|---|
| `data/raw_data/water-cfd-raw.xlsx` | 原始水 CFD，D-4…G-8 每几何 188×45（40 几何 × ~47 点） | (K,cF) 光滑基拟合源（CF-REFIT 收尾输入） |
| `TPMS水_关联式拟合CFD工况.xlsx` | 汇总 1880×25 + 几何表 | 交叉校验 |
| `试验记录表_整理版.xlsx` | SLM 试件台架，Diamond_汇总 178 行 / Gyroid_汇总 218 行，L×t 编号试件 | **空气侧 γ 锚唯一实验源**（col47；CFD 对照列不作拟合基） |
| `20260401-上海电气…xlsx` | 上海 16 例 HX 实验 | **纯盲考卷**（loader 已有 `_assert_no_shanghai_leakage`，D-1 延伸到 γ 层） |
| `换热器压损——G-7-6+D_7_6.xlsx` 等 7-6 系列 | 7-6 试件 HX 级压损（气/水侧） | 盲考卷二（L=7 外推方向；γ_df 454 vs RBF 745 盲测数据源） |
| `sCO2-CFD/{Diamond,Gyroid}/` | 光滑壁 RANS ~7000 例（缺 D_7_6 部分、G L=7 全部、G_6_6 大部） | sCO2 光滑基（已入产线）+ 试点拟合域 |
| `sCO2-Experient.xlsx` | D-7-6 51 + G-7-6 44 例（sCO2-sCO2 逆流 HX） | **sCO2 γ 标定源**——既是标定源不再当盲考（域内只做 LOO/holdout+反向检验） |
| `_prebuilt/*.csv` | 现行 K 面 / SmoothDF / RBF 锚表 / sco2 cF 表 | 对比矩阵"现行"列冻结参照 |

明确不用：上海 16 的任何拟合/标定用途；试验记录表 col27-35/44 CFD 对照列；
L4/L5 弃锚（台账证伪：原始 col43 粗糙 ≤ 光滑，物理不通；重仲裁需新粗糙壁 CFD，不在手）。

## 3. 现行 γ 锚提取链（file:line）与 C8 口径裁定

```
试验记录表 col47（摩擦压损 = 实验总ΔP 去入口效应 × 转折f/f 摩阻隔离）
  → df_surrogate/load_data.py:57（_COL_DP_CORR=47；docstring :13-24 记载列语义）
  → 闭式动量拟合 dP = (μ/K·u + ρ·cF·u²)·L_channel（load_data.py:21-24 声明；
     逐试件提取，产 _prebuilt/{Diamond,Gyroid}_surrogate_ref.csv）
  → surrogate_v3.SurrogateV3.ref（逐 (L,t) c_F）
  → gamma_df.GammaDF.anchors（gamma_df.py:124-133）
  → γ_anchor = cF_exp / cF_smooth(Re_ref=2530)（:131-133，可信层 L∈{6,8}）
```

**裁定：试件锚是闭式反演，不穿 SIMPLE 求解器 ⇒ C8 压力水平口径不进试件锚。**
唯一被求解器口径缠住的是 **L7 Gyroid = 534.8**（`gamma_df.py:63 GATE_CF_G7`，
docstring 自述 "Shanghai calibration"，Gyroid L 方向 log-二次插值穿过它
——出身 = 2026-04 上海 dP 标定，穿旧口径栈〔velocity-inlet→massflux 前、C8 修复前、
F2 前〕调出；精确沿革见 vault/reports/2026-04-17-shanghai-dP-error-analysis-CN.md §11
与 2026-06-12 gamma 多保真文档）。**按边界 2 它退役**：Gyroid L 方向改照 Diamond
模式（log-线性 L6→L8，D_7_6 盲测已验证该模式 454.2 vs ~454）。
待核尾巴（D-2b 顺手）：闭式反演用常 ρ（col12）——核一眼试件 max(Δp)/P 量级，
声明不可压反演的适用性（预期 ≪1，成立）。

## 4. sCO2 试点的修正关联式（subst.v2 工程取用卡解剖）

来源：主检出 `reports/sco2_exp/sco2_exp_vs_cfd_subst.v2.html`；产卡脚本 = 主检出侧
`validation/sco2_exp/compare_exp_vs_cfd.py`（**worktree 分叉后已更新**，md5 不同，
D-1sc 第一步收编差异）。卡片形态：

- `f = γ_f(Re)·f_cfd`，`γ_f(Re) = Γ₀·Re^Δ` = 实验 f 幂律（分 hot/cold）÷ CFD D-F
  曲线窗内同形幂律（`compare_exp_vs_cfd.py` `_fit_power`/`f_cfd_fit`/usecard 节）。
- 卡片自带警示：仅实验窗内插值；**cold 侧 Δ 物理不合理（压差近传感器地板）禁外推**；
  hot/cold 不一致是数据事实；基准 = 产线光滑壁闭合（SCO2_NU_COEFFS + sco2_df cF）。

### 试点四护栏（iter 59 与 Alex 对齐）

1. **修正只落 cF 提取步**：γ_f×(A/Re+B) 非 D-F 形——直接重拟全曲线会把幂律曲率
   错灌进 K。实验窗内 Darcy ≤4%，γ_f 乘 Forchheimer 平台即可；**K 守水侧锚**
   （流体无关已双向反验坐实）。
2. **Δ 作 UQ 变体**（自由 vs 0），差异传播到 Δp 带；窗内预期二阶，若不是自动升级
   为决策点。
3. **hot/cold 量化后再裁**：三变体（hot/cold/合并宽带）跑到 Δp 预测带，证据包交
   Alex 选侧（cold 幅值与空气 D-7-6 历史 ~3.4× 一致、斜率可疑；hot 平台本身可疑）。
4. **Diamond 承重**：G 侧 CFD 基线是 L 方向外推（G L=7 CFD 全缺），γ_f_G 带混杂，
   并行但标注；D_7_6/G_7_6 CFD 补算到位后重估（触发器）。

## 5. 验证口径冻结清单（考卷跑分用，D-3 前 golden/BASELINE 不动）

- 求解器栈：massflux inlet（两维默认）、F2 收敛门（管线默认）、面提取 dP、
  `TPMSHX_CONV_MODE=f2` 显式钉（C11 教训）、PYTHONHASHSEED=0 + 线程钉。
- **打靶 ON（`TPMSHX_P_IN_SHOOT=1`）为新验证口径**——γ 只锚试件/实验后，求解器
  口径不再进锚点，打靶是纯验证侧选择（物理更正确）；正式翻默认在 D-3 一次重基准。
- 网格：上海门 20×10×3（与 BASELINE §3 同）；kernel-direct runner 不作考卷
  （O2：门必须走生产管线）。
- 外推压力题必考（RBF D7 灾难史：端到端 67.4% RMSRE）。

## 6. 台账证伪史复核（防重蹈）

- **rbf D7 外推灾难**：RBF 在 (L,t) 网格外外推 745 vs 真值 ~454（gamma_df docstring
  scoreboard）——一切新面必须过 7-6 盲题。
- **L4/L5 弃锚**：原始数据粗糙 ≤ 光滑，物理不通（gamma_df docstring :25-27）；
  flat6 延拓 + 声明带。不重启除非新粗糙壁 CFD。
- **CF-REFIT 搁置因由**（台账）：两段法 K 已切、cF 刻意保留实验锚——因为当时唯一
  的 cF 实验真源就是试件锚。候选 D 的新架构（CFD 形状 × 实验幅值）与其不冲突：
  D-2a 只升级 cF_smooth 的"形状面"，幅值仍归 γ。
- **C8 定价教训**（openspec/changes/archive/c8-p-in-shooting/design.md §6）：
  口径修正与 γ 重锚必须同波——本章程即其制度化。

## 7. D-1sc 已知待办（本审计移交）

- 主检出 `compare_exp_vs_cfd.py`（07-16 版）与 worktree 版 diff 收编——subst 逻辑
  只在主检出侧，worktree 需带上（只读主检出、拷贝进 worktree 提交）。
- sCO2 考卷四题固化：LOO/holdout（标定-验证分离纪律）、反向检验（sCO2 系数回预测
  水 CFD 1269 点）、窗内守卫（Re 窗外 fail-loud）、现行光滑基跑分基准。
