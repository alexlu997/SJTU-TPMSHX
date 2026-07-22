# 进度日志（PROGRESS）

每轮一段：`## iter N · 日期 · 条目`，正文写"做了什么 / 验证证据 / 下一步"。重基准条目用 **⚠** 高亮。

## iter 65 · 2026-07-22 · 数据治理问答轮（Alex 插问）——**"中间胞元 vs 三段平均"实测裁定 + Gyroid 体检 + 入口段污染发现**（docs-only）

- Alex 问：Diamond sCO2 CFD 有核心三胞元逐段与三段平均两套，用哪个？Gyroid
  是否处理好？
- **实测（4000+3000 例 × 3 段全量）**：Nu 的 s3/s2 = 0.998/0.9995（D/G，
  发展段坐实），s1/s2 = 0.867/0.839（入口段低 13-16%）⇒ 三段平均把 Nu 拖低
  9-11%——**Nu 必须用剔入口后的 2+3 段**（现行 fit_nu_sco2 约定正确；只用
  中间段白扔一半样本）
- **发现：f 的入口段污染不对称**——s1/s2 = 1.03（D）/**1.49（G）**；整核
  (3段) f 对发展段(2+3)：D 1.00（侥幸相消）、**G ×1.168**。现行 sCO2 cF 基
  （load_core 整核 dp）在 Gyroid 侧比周期发展值高 ~17%；真实 HX ~26 胞元中
  入口占比仅 ~4% ⇒ 闭合应取发展值。产线无恙（γ_f 锚在 7/0.6 base-relative
  自洽吸收），但 **G 数据补齐重拟时 cF 基应换 s2+s3 段 dp**（换基绊线会响，
  γ 按流程重定）——触发器登记
- **Gyroid 体检**：已上传 3000 例文件健康（每例 3 段齐、Nu/f 零 NaN、12 几何
  G_4_3..G_6_6）；"没处理完"= 上游缺口（L=7 全部 + G_6_6 仅 30 例），
  正是解 G 侧 γ 混杂的关键批次
- **对 D-2a 的直接影响**：water-cfd-raw 与 sCO2 同一后处理管线——水侧 dp
  是否同样整核含入口？**D-2a 首步新增此核查**（若同构，现行 K 面与待建 cF
  面同承此偏，量级待测）
- 下一步：D-2a 继续（首步 = 水侧 dp 口径核查）

## iter 64 · 2026-07-22 · D-2sc-4 Gate A 复臂 ✅——**修正闭合过 GOLD 门（4.2%/8.1%），sCO2 试点全链闭环**（`61cb1e2`）

- Gate A 实跑 PASS：GOLD 6 例 duty 误差 +2.1/−0.6/+5.4/−3.0/−8.1/−0.5%
  （RMSRE 4.2%，max 8.1% < 15% 门，bias −0.8%）——γ 修正端到端达
  compute 链、UA/ε-NTU 装配正确。窗纪律可见：case 20/37 热侧 Re 低于窗
  下沿→回落光滑→恰为误差最大两例。诚实注记：GOLD 属拟合同族（域内
  一致性验证非盲考）
- 机械债两处修复：validate_sco2_d76.py 包名导入（projects/703 未进
  P1.8b；死导入曾被 try/skip 吞虚绿）+ XLSX 平铺路径（同源实证：三案例
  ṁ/T/Q 六位全同；列图左移一列→**表头守卫式列图**制度化）
- 套件 1306+10 绿，**skip 4→3 顺带解开 P0.1 悬案**（第 4 个 skip = 本门）；
  golden 双位同；定时器重建（8f180729，armed 07-22）
- **sCO2 试点收官**（iter 60-64 五轮）：考卷→六变体证据→D6 hot-free→
  γ_f/γ_Nu 双侧入产线→GOLD 门复臂全过。sCO2 Δp/Nu 语义 = 窗内 HX 级
  实验修正 + UQ（σln 冻结），窗外响亮回落光滑
- 下一步：水/空气阶段 D-2a（CF-REFIT 收尾）

## iter 63 · 2026-07-22 · D-2sc-3 γ_Nu 入产线 ✅——**sCO2 换热侧修正落地（幅值制）+ Gate A 复臂堵点揭出**（`11289db`）

- γ_Nu 常量+函数落 nu_correlations.py 本体（单源合规）：D 1.7558 窗
  [8950,35174]（ok_dT 滤后窗比 γ_f 窄）/ G 1.0744 窗[10632,48961]（混杂
  注记）；幅值制有数据依据（Re 斜率 ±0.02 平——γ_f 的 hot 斜率显著故函数制，
  两者形制不同皆由测量定）
- 双消费点：fluid_props._nu_sco2（注册表）+ flux_3d._sco2_hv_local_field
  （3D 局域 T，γ 在层流地板前）；逐元素窗混合（场横跨窗界时逐格处置）
- nu_sco2_topo 保持光滑（验证无回灌）；audit D3 kill-switch 钉光滑链；
  routing 测试期望升级 γ×光滑；测试 +10（含双分支确定性 hv 探针——首版
  容忍双分支被识别为无牙，收紧）
- **Gate A 发现**：物理触发器满足（历史 ~1.7× vs γ=1.756）但复臂被机械债
  堵住——projects/703 全目录死导入（P1.8b 未覆盖，exec_module 失败被
  try/skip 吞成虚绿——"验证工具不跑生产路径"翻版）+ XLSX 路径失效；
  skip 文案改诚实，复臂 = D-2sc-4
- 门：套件 1305+10 绿（4:51）；golden 双位同；ruff 净

## iter 62 · 2026-07-22 · D-2sc-2 产线接线 ✅——**sCO2 Δp：光滑壁估计 → 窗内 HX 级修正**（`c98d1e6`）

- 新模块 `df_surrogate/sco2_gamma_f.py`（D6 hot-free 全精度冻结常量）乘进
  `predict.sco2_cf_scale` 咽喉点——2D/3D/compute 三路零改动；窗外一次性
  警告回落光滑壁（绝不外推斜率）；kill switch TPMSHX_SCO2_GAMMA_F=0
- **双计审查**（invariant-guard 钩子触发）：sCO2 路径 /base 比值本就消掉
  空气 γ，γ_f 是分支唯一实验因子——不双计；未来双计入口（sco2_df 烤
  粗糙度）红线段堵死；验证 f_cfd 直连光滑基（无循环定义）
- 测试 +11 全绿（含**换基绊线**：活重拟 vs 冻结常量 1e-9——sco2_df/K 面
  一动即红）；套件 1295+10 绿（4:51）；**golden 3D/2D 双位同 = air/water
  零漂移实证**
- Alex 轮中问"必须用 RBF 吗"→ 答：非必须——在 7/0.6（一切证据所在）
  修正乘积对基插值误差不变（γ≡exp/base 自洽消除）；基形式只影响 (L,t)
  迁移，且已被换基绊线锁死；D_7_6/G_7_6 CFD 补算落地后可直拟消插值
- 台账红线状态：SCO2-CFD"光滑壁禁选型"在实验 Re 窗内解除（Δp 侧）；
  Nu 侧待 D-2sc-3
- 下一步：D-2sc-3 γ_Nu 接线评估 → D-2sc 收案 → 水/空气阶段

## iter 61 · 2026-07-22 · D-2sc-1 六变体证据包 ✅——**D6 已决：hot 侧（Alex 快裁+证据坐实），Δ 子选择 hot-free**（`349f466`）

- Alex 轮中快裁："我们就选择hot侧，因为这个趋势与cfd的趋势是一样的，cold侧
  的趋势不对"——D6 记已决（原话入档）
- 证据（gamma_f_variants.py，贝叶斯解析后验 + f≡Δp 恒等式，无需求解器）：
  own medAPE **hot-free 2%/1%**（D/G）vs cold 16-31%、pooled 23-45%；hot 68%
  带覆盖 80/84%（UQ 诚实）带宽 ±6.0/3.7%；pooled 带 ±54-64% 报废；跨侧
  52-143% 存档两侧不可调和；γ_air 参照 75-78% medAPE = HX 级系统效应份额
- **产线取用式**：γ_f^hot(Re)=Γ₀·(Re/Re_c)^Δ——D (6.86, +0.126, σln .059)、
  G (7.77, +0.098, σln .036)，窗内插值 only
- 门：套件双 pass 绿（pipefail+READY；pass-1 计数行被 tail-4 截掉——教训：
  留宽尾巴；本轮零新增测试 ⇒ 1284 不变）；ruff 净；脚本实跑 exit 0
- 教训：pandas 列名 `eval` 撞 DataFrame.eval 方法（属性访问恒 False）
- 下一步：D-2sc-2 产线接线（sco2_cf_scale × γ_f^hot(Re_in)，窗守卫，
  air/water 位同证明）

## iter 60 · 2026-07-22 · D-1sc sCO2 考卷 ✅——**四题记分板落地，基准冻结，两项首跑发现**（`0ba9bcd`）

- **收编题**：worktree 基点已含 07-16 subst 全机器；主检出未提交微调 = 报告改版
  死导入（会触 F401），裁定不移植；报告脚本 worktree 实跑 exit 0，双报告再生
  （tracked CSV 位同）
- **考卷**（exam_sco2.py，一键跑分 → exam_sco2.csv）：BASE 光滑基 γ 带 / HOLD
  幂律 LOO+Re对半 / XFLUID 跨流体独立轴 / GUARD 窗守卫（数据自导出窗，窗外
  OutsideExperimentalWindow fail-loud，D-2sc 必须 import）
- **发现①**：hot 侧 γ_f 函数性稳定（D 7.00·fn 1.98·Re^+0.126，LOO 2.0%；
  G 7.85·fn 2.91·Re^+0.098，LOO 1.3%）；cold 侧幅值可信（4.19/3.33，与历史
  3.4× 连续）但函数性崩坏（指数 +0.93/+1.99，Re对半 37-48% = 传感器地板）
- **发现②**：sCO2 γ_f ≫ 空气试件锚 γ_air(7/0.6)=1.53/1.96（独立轴，D_7_6
  空气盲测验证过）——超额 ×1.7-4.6 ⇒ **修正卡 = 粗糙度 + HX 级系统效应**，
  适用面须标"HX 级预测修正"；3.4× 历史参照纠为同族口径非独立轴
- 门：套件 1284+10 绿（3:53）；Alex 中途问"上海门是水/空气怎么验证 sCO2"
  ——答案即考卷设计本身（见回复），已固化进 exam_sco2 docstring
- 下一步：D-2sc 修正试点（六变体 + UQ + 选侧证据包）

## iter 59 · 2026-07-22 · D-0 溯源审计 ✅ + Alex 二次拍板"sCO2 先行"（docs-only）

- **两次 Alex 交互**：①"先告诉我你会用到哪些数据"→ 数据资产地图（8 类资产逐一
  实测核过，角色=拟合/标定/盲考/不用，见审计 §2）；②"CFD f 与实验 f 差距大，
  用 subst.v2 关联式先修 f 再提系数；sCO2 数据多，先做 sCO2？"→ 赞成+四护栏，
  章程重排（D-1sc/D-2sc 前置，水/空气 D-2a/b/c 排后同工具链）
- **D-0 核心裁定**（docs/DF-CALIBRATION-AUDIT-2026-07.md）：试件锚提取链钉到
  file:line——col47 → load_data:57 → 闭式动量拟合（不穿 SIMPLE）→ surrogate_ref
  → gamma_df:124-133 ⇒ **C8 口径不进试件锚**；唯一纠缠点 = L7 Gyroid 534.8
  （gamma_df.py:63，上海标定穿旧口径栈）——按边界退役，Gyroid L 向改 Diamond
  模式（该模式 D_7_6 盲测 454.2 vs ~454 已验证）
- **subst.v2 卡解剖**：γ_f(Re)=Γ₀·Re^Δ（实验/CFD 同形幂律相除，分侧），卡自带
  仅窗内/cold 禁外推/两侧不一致警示；产卡脚本在主检出侧已更新（md5 异），
  D-1sc 首步收编
- **四护栏**：修正只落 cF 提取步（K 守水锚）；Δ 作 UQ 变体；hot/cold 量化后
  Alex 裁；Diamond 承重 G 标注混杂。方法卫生：D-7-6/G-7-6 既标定不盲考，
  sCO2 域内 LOO/holdout+反向检验，真盲考在水/空气阶段
- 下一步：D-1sc sCO2 考卷基建

## iter 58 · 2026-07-22 · 候选 D 立项对话轮 ✅——**方向与边界四点拍板，D-0..D-4 章程入 ROADMAP**（docs-only）

- Alex 发起（"我现在想开候选D了…制定大方向以及边界"）。循环先侦察事实底座
  （gamma_df 解剖：cF_smooth×γ、K=CFD-refit；γ 锚两类——col47 试件锚 L6/L8 +
  **L7=534.8 上海标定点**〔穿旧口径求解器栈调出，C8 纠缠所在〕；sCO2 γ 分析已
  完成待裁；CF-REFIT 搁置半成品；本机无 CFD 求解器），再以 4 问收敛边界。
- **Alex 四点拍板**：①主目标 = 全串行 a→b 一次批到位（约 7-9 轮，关键决策仍停）；
  ②数据边界（原话）＝"主要用cfd数据来'拟合'D-F的两个系数，然后用实验数据来标定
  （具体用哪些实验数据，我认为这里不要用到上海电气的那16个case）"——**上海 16
  退出标定转纯盲考卷**；③sCO2 并入、排空气侧重锚后；④UQ 要（γ 后验+Δp 带）。
- **两个直接推论已向 Alex 声明**：头条重新定义为盲预测精度（预期变大、科学声明
  更硬）；γ 只锚试件后求解器口径不再进锚 ⇒ C8 打靶翻转在 D-3 一次重基准解决。
- 产出：ROADMAP 候选 D 展开 D-0（溯源审计）→D-1（考卷基建）→D-2a/b/c（cF 基
  升级/γ 重锚+UQ/方法对比）→D-3（换默认+重基准+打靶翻转）→D-4（sCO2 翼）。
- 下一步：D-0 溯源审计开工

## iter 57 · 2026-07-22 · C8 打靶循环 ✅——**能力入库（opt-in）+ 定价否决默认翻转：γ 锚点吸收了旧口径偏置**（`0519587` + 归档）

- **Alex 点名开工**（"可以，我们先把C8做了"）。台账 C8 遗留：1D 种子只是估算，
  解出进口绝对压 ≠ 指定 P_in（case 16 差 −5.2%），全场密度水平偏置
- **实装**（openspec c8-p-in-shooting，已归档）：两维外循环用**实测阻力**做 P²
  重种子（`P_out²_new = P_in² − Δp·(Δp+2·P_ref)`，不动点=实现进口压恰为 spec，
  1–2 发命中）；3D 走同一 `_seed_p_ref` choke 门，2D 保持 O1 clip 姿态；旋钮
  cfg `p_in_shooting` > env `TPMSHX_P_IN_SHOOT` > 默认 OFF；诊断键
  `P_in_realized_A/B` 恒发射（OFF 偏差首次可见）；evaluator 不打靶（O2）
- **门**：套件 1284+10 绿（+8 新测试，3:34）；golden-3D 位同；golden-2D 对
  改码前现场基线位同——knob OFF 零行为漂移
- **定价（ON）与否决**：3D 上海 case 12 起 **in-model choke**（Δp/P≥0.52 四例
  全不可行）、完成 11 例 err_dP 单调劣化 +2~9.4pp；2D RMSRE_dP **8.62→10.73%**；
  golden air_air 15³ ON 亦 choke（B 侧工况点本就 Δp/P=53% 隐蔽越谱）。
  **机理**：γ_df 是穿旧口径（实现进口压随 1D 种子误差漂移）标到实验 Δp 的，
  打靶拆掉这层约定性补偿→闭合真误差裸露。A2 同构——**口径修正必须与 γ 重锚
  同波**（候选 D 耦合律第二例）。DECISIONS **D5** 记录岔路与重启触发
- **新能力副产品**：打靶把"1D 盲重种子滑过的动态 choke"变成响亮 raise
  （测试锁定）；golden air-B 隐蔽越谱是它照出来的第一个真发现
- 下一步：回待命（候选池余：B 科研支撑 / D D-F 方法【含 C8 翻转前置】/ D4 尾账两枚）

## iter 56 · 2026-07-22 · D4(b)-2 实装+重基准 ✅——**⚠ golden ULP 级重基准；全门 19min→3.5min 闭环**（`2edcb7c`）

- _AMG_GATE 30k→2k（一行+曲线全数据注释；护栏钩确认声明式重基准路径）
- **§5 重基准**：golden 27 标量全 ULP 尾级（max rel ~5e-12）——物理未动只舍入尾变；
  json+meta 同 commit 带 `!`，meta history 记录证据链与幅度
- 验证链：golden 自证位同 PASS + 套件 **1276+4skip（3:31）**（wall_refine 459→151s）+
  Shanghai **GATE PASS 4.88%/2.12% 分毫未动**（600 格留 LU 侧，围栏性质实证）+
  CSV ULP 自改写惯例回退
- **D4 战果（iter 53-56 四轮）**：全门 19min（P3.1 前）→11.5→7.7→**3.5 分钟**；
  中带 pp 4-23×；测量三件套工具入库可复现。尾账两枚非阻塞（40³ 探测/L11 复活）
- 下一步：D4 全项闭环 → 回待命（候选池余：B 科研支撑、D D-F 方法、C8 打靶循环、
  P1.8b 后续者无——ROADMAP 全清状态维持）

## iter 55 · 2026-07-22 · D4(b)-1 成本曲线 ✅——**AMG 全带碾压，裁定门 30k→2k**（`94d6208`）

- 5 网格 × 2 方案 × 11 pp 调用直测（shim 计时）：AMG 4.4×/14.7×/22.6×/8.9×/22.4×
  全带碾压 LU；门沿 29.8k 处 LU 病态 4.9s/次；零 bcg 失败、漂移重建机制健康
- **裁定 _AMG_GATE 30,000 → 2,000**。围栏：Shanghai 600 格留 LU ⇒ headline 位同；
  golden 15³ 翻 AMG ⇒ §5 重基准（已授权）；wall_refine 预期 448→~20s
- L11 rtol_dyn 复活降级后续项（F2 门兜底）；旗标 bcg_t 计数器疑双计、partial-BC
  40³ 挂死构型入实装验证矩阵
- 测量-only 免门；夹具入库 upgrade/tools/d4b_pp_cost_curve.py
- 下一步：**(b)-2 实装+重基准轮**（一行门改 + §5 全流程 + 全门 + Shanghai 位同证明 +
  conservation/wall_refine 复验）

## iter 54 · 2026-07-22 · D4(c) profile 轮 ✅——**pp LU 重分解 89.4%，(b) 设计改写**（测量-only）

- wall_refine"异常"解剖：所谓 288 格实为细化后 **24×22×22=11,616 格**（40× 膨胀）；
  435.8s 中 **pp 占 89.4%**（818 次 × 0.48s/次），LTNE 仅 87s；uniform 对照 0.8ms/次
  ——40× 网格 600× 单次成本，与稀疏 LU fill-in 超线性标度吻合
- **根因**：11.6k < _AMG_GATE=30k ⇒ 直接 LU 且每 SIMPLE 迭代重分解——成本在分解
  不在收敛，与拉伸网格条件数无关
- **(b) 设计改写**：主战场=中型网格带（2k–30k）pp LU 重分解；候选①下调 AMG 门
  （先量中带成本曲线）②符号分解缓存 ③中带迭代解。rtol_dyn 复活仍在列（C7 数据）
- 旗标两枚：partial-BC 夹具 40×40×20 静默挂死（(b) 验证矩阵须含）；32k pp 占比
  未直测（C7 台账 wall 2.10× 可用作 (b) 定价基线）
- 复现脚本入库 upgrade/tools/d4c_pp_profile.py；测量-only 免门
- 下一步：**(b) 实装轮**（先量 2k-30k 中带 LU vs AMG 单次成本曲线定 gate 新值/方案）

## iter 53 · 2026-07-21 · D4(a) 巨兽测试节食 ✅——**全门 11.5→7.7 分钟，预测命中**（`7061836`）

- Alex 拍板 D4="a、b、c 全做，做就做完"。(a) 先行：实测驱动的逐案例网格
  （T3@16 余量 0.28% / T4@18 余量 0.73%——@16 的 0.96% 太薄弃用），T1/T2/T5/T6 留 20
- **顺带旗标真异常**：wall_refine 剖分 refined 447.7s vs uniform 0.6s（288 基格 750×）
  ——拉伸网格求解病理，交 (c) profile 轮头号样本，刻意不节食（掩盖异常=反向操作）
- 事故二犯记档：& 分离（iter51 同款）早期拦截清场归零；教训写**持久记忆**
  （no-shell-detach-in-bg-commands）防三犯
- 门证据：套件 **1276+4skip（7:44，关键路径=wall_refine 459s 预测命中）/ 10 绿** +
  **GOLDEN: PASS (bit-identical)**；六案例序列验证 6/6（11:48）
- 下一步：D4(c) profile 轮（wall_refine 异常 + pp/AMG 占比 → 为 (b) 供弹）

## iter 52 · 2026-07-21 · C-2 性能余项盘点 ✅——**两硬项一跑法建议，立 D4 待拍板**（docs-only）

- 底料：iter51 durations 谱（604/526/459s 三巨兽单测=全门关键路径地板）、台账 C11-L11
  （AMG rtol_dyn 调度器被 C6 证伪残差驱动而实质已死）、FINAL-REPORT C1 原案、
  HANDOFF §6c（ctrl6 臂 144 初始点÷2 worker）
- 盘点结论：真候选仅 **(a) 巨兽测试节食**（1-2 轮低险，全门 11.5→7-8 分钟）与
  **(b) AMG 调度器复活**（真求解器性能项但大概率 golden 重基准）；(c) profile 战役
  边际信息量存疑可并入 (b) 前置；其余（2D 预算/缓存面/BO 吞吐/串行遍）均已被
  F2/P3/O2 契约消化，非项
- 产出：DECISIONS-NEEDED **D4**（四选项+跑法建议附注），循环建议 (a) 先行
- 验证：docs-only 免门
- 下一步：待 Alex 拍 D4；期间回待命纪律

## iter 51 · 2026-07-21 · C-1 线程钳制时序修复 ✅——**HANDOFF §6b 闭案 + 一次孤儿进程事故**（`6fc752b`）

- 现场核实缺陷比记载深一层：spawn 反序列化 worker 必先 import 模块（顶层 numpy）
  → OpenBLAS 库加载即读环境 ⇒ **函数体内钳制结构性恒迟到**；清单漏 NUMBA_NUM_THREADS；
  setdefault 输给外泄 shell 变量
- 修复三件：轻量叶模块 `_thread_caps.py`（仅 os）任 executor initializer（反序列化
  只拉轻模块，钳制先于 numpy/numba）；补 NUMBA + 硬设 + TPMSHX_WORKER_THREADS 逃生阀；
  时序契约测试 4 断言（真 spawn 池实证 pre=0/blas=1/numba=1）
- **事故记档**：首发门命令 bash 内 `&` 二次分离 → bash 退出撕裂管道 → **197 孤儿
  xdist worker**（日志冻结）→ 按 venv 路径过滤精准清场归零。教训：后台门整命令交
  run_in_background，禁 shell 内二次分离
- 门证据（干净重发）：套件 **1276+4skip（11:28）/ 10 绿**（+4=新时序测试）+
  **GOLDEN: PASS (bit-identical)**；HANDOFF §6 改已解 + atlas 注记
- 下一步：候选 C 余项盘点（profile 先行纪律）或待 Alex 排新优先级

## iter 50 · 2026-07-21 · A2 调查即关闭 ✅——**动机亏空三重证伪，D3 剧本 3D 重演**（`ff99e92`）

- Alex 拍板启动 A2（+C 随后）。按台账纪律先查 vault 台账——**C10 与 D3 前提正面冲突**
  （C10：捕获=prescribed v × 初始 ρ(T_in,P_in)；D3：出口基准亏 19.3%）
- 三重证据裁决 C10 对：代码链（stages:736/评估器:247 物理标量→构造平铺→solve 入口
  捕获）+ **仪器实测 0.9951**（出口基准应 0.912；探针入库可复现）+ 台账独立记载
- **19.30% 与 2D 7.38% 同源自 iter 10 的 1D 种子算术误读**——D3 调查的两维亏空估算
  全体系假象（iter 41 杀 2D 半，本轮杀 3D 半）
- 新发现（良性）：真实偏移=首格中心播种压半格约定（0.49%，网格收敛消失）；
  2D 钉面基准——两维差半格约定非物理分叉
- 三件套（golden 重基准/Shanghai 重验证/γ 重锚）**全部未动用**；绊线 4 断言全程绿
  且 docstring 已修正；幸存机会（C8 打靶循环）归候选池
- 验证：契约 6/6 + ruff；零库代码（docstring-only），免全门有据
- 下一步：**C 性能纵深**（parallel_runner BLAS 上限计时缺陷首项）

## iter 49 · 2026-07-21 · P1.8b F3 五阶段迁移 ✅——**P1.8b 七轮全波次收官，Phase 1 全清**（`0816d9f`）

- run_stack_3d.py 3001→68（编排器+24 名重导出）；run_stack_3d_stages.py 2977（verbatim）
- 首跑 1 败教科书案例：eps 负向守卫往编排器命名空间打补丁——阶段 globals 已随迁，
  重导出只会让补丁**无声空转**；改打 stages 模块+编排器双引用，并全测试审计确认
  唯一站点（防同类假绿）
- 门证据（终跑）：**1272+4skip（10:23）/ 10 绿 + GOLDEN: PASS (bit-identical)**
- **P1.8b 战果（iter 43-49 七轮）**：~350 文件迁包名风格、135 个 sys.path 引导块退役、
  垫片 W0 立 F2 撤全程零行为漂移、golden 六连位同、Shanghai headline 分毫未动；
  openspec p18b 变更归档。ROADMAP 至此**唯一余项清零，Phase 0-4 + P1.8b 全部完成**
- 下一步：A2（3D 物理 G 统一调查，Alex 已拍板）→ C（性能纵深）

## iter 48 · 2026-07-21 · P1.8b W_final-F2 撤垫片 ✅——**包风格成唯一约定，两轮门红全教训**（`79e5c21`）

- Fable 直做（最高风险轮）。__init__ 纯 docstring、logutil 打包中立（removeprefix）、
  cli/main 双约定改造、mypy 仓库根基底、身份测试改撤除态 4 断言
- **门红 #1（257 败 53s）**：字符串形模块路径历波刻意不碰、全靠垫片兜底——patch 目标 11 +
  import_module 参数化数据表 13 + 子进程内嵌 sys.modules 键 3（旧键断言**空转假绿**，
  比红灯阴险）；外加 configs 包历波白名单遗漏（语句形 8）。24 站点断言计数修毕
- **门红 #2（232 败）**：numba 磁盘缓存按旧模块名序列化——56 个 .nbi 反序列化时
  import 'solvers' 即溃（解释了 wiring 文件单跑绿/内核测试齐溃的分裂现象）。
  清 __pycache__ 纯派生物，重编译一次性成本已摊
- 扫尾：from tests. 跨测试导入 4 处 → pytest 同名直导；身份测试自咬一次（raw grep 被
  docstring 叙述打中 → AST 零语句断言）
- 门证据（终跑）：套件 **1272+4skip（11:31）/ 10 绿**（计数对账 1275−7+4）+
  **GOLDEN: PASS (bit-identical)** + 18/18 靶向 + tpmshx-run
- 下一步：F3 = P1.5 尾巴（五阶段函数文件级迁移，可选收尾）或经 Alex 裁决直接归档
  openspec 变更（迁移主体已全毕）

## iter 47 · 2026-07-21 · P1.8b W_final-F1 库内改写 ✅——**最大单波 78 文件纯替换**（`d672eba`）

- Sonnet 委托：**AST 列级改写**（ast 定位 import 节点字符列纯文本插入——三波行尾
  教训的方法终态，339+/339- 零搅动）；Fable 复核零越界 + type gate 风险探针
- 覆盖库内 8 目录 + tests/design 15 余量清账；相对导入不动；零行为变化（垫片在位）
- cli.py / main.py **有据整体跳过**：双约定引导块 + 裸启动双模式支持，是 F2 撤垫片的
  正题而非本波机械范围——代理判断准确未扩权
- 分析器免修：audit_import_graph 本就剥前缀双约定兼容（文档串明写），layering/dag
  前后 0 违规一致；我预判的 mypy found-twice 实测未发生
- 门证据：套件 **1275+4skip（19:13）/ 10 绿** + **GOLDEN: PASS (bit-identical)** +
  ruff 全包 + tpmshx-run exit 0
- 下一步：**F2 撤垫片收官**（全库残留零核对 → 撤 finder/自举 → __init__ 瘦身 →
  cli/main 双约定改造 → 身份测试改撤除断言 → mypy 基底换仓库根 → pyproject/atlas 收尾）

## iter 46 · 2026-07-21 · P1.8b W3 runs+ui ✅——**golden 门脚本自迁自证**（`1f0e689`）

- Sonnet 委托 + Fable 复核；runs/ 31 + ui/demo_vis_3d，净 -61 行；archive/ 冻结区零 diff
- **golden 门脚本本体随波迁移**（_golden_3d/_golden_2d：守卫核实 import 零副作用），
  波门 golden 实跑 = 迁移后门脚本自身冒烟 → **GOLDEN: PASS (bit-identical)**
- 零逃生舱（本波引导块全数干净可删）；9 文件零改动有据；AST 遍历双保险残留全零
- 自伤 1 处：孤儿 Path import 被**套件内 lint 门**抓获——常驻门在委托流程的首次实战拦截
- 门证据：套件 **1275+4skip（18:52）/ 10 绿** + ruff 全包 + 身份/wiring 组
- 下一步：**W_final**（库内 165 模块改写 + 撤垫片 + design 余量 + P1.5 尾巴）——
  P1.8b 最后一波，量级最大，或需拆两轮（改写轮 + 撤垫片轮）

## iter 45 · 2026-07-21 · P1.8b W2 validation+df_surrogate ✅——**headline 位同直跑冒烟过**（`59ee773`）

- Sonnet 委托（逐文件手改非批量正则——W1 的 CRLF 模板教训直接改了执行方式）+
  Fable 复核（零越界、ruff、wiring/身份 21/21、gate 脚本 diff 抽查）
- 31/44 文件改动；3 逃生舱有据（script-dir insert 供 sco2 兄弟脚本裸名互导，非包根
  引导）；13 零改动有据
- 代理自伤两处自查修复：3 文件整文件 CRLF→LF 翻转（字节级行尾审计）、孤儿 Path
- **W2 特有波门全过**：validate_shanghai_3d_real 包风格下直跑 **GATE PASS 且 headline
  分毫未动**（RMSRE_dP 4.88% / RMSRE_Q 2.12% ≡ P0.1 基线）；tracked CSV 的 ULP
  自改写（1.4e-12）按 iter 1 惯例回退
- 门证据：套件 **1275+4skip（19:08）/ 10 绿** + **GOLDEN: PASS (bit-identical)**
- 下一步：W3 = runs/ 35 + ui/ 1 迁移（直跑脚本逐个冒烟）

## iter 44 · 2026-07-21 · P1.8b W1 tests 迁移 ✅——**§10 委托轮：141 文件净 -357 行**（`140166b`）

- Sonnet 子代理机械执行（脚本化改写非盲扫 + 分批自测 + 三项强制收尾自检），Fable 复核
  （改动面 143 精确、独立 ruff/grep、关键组 78/78 抽跑、diff 抽查含混行尾文件）
- 实际 141 文件（预估 73 系当年只数了含 sys.path 的文件；另 68 个只有顶层导入无引导块）
- conftest 引导块 → `import sjtu_tpmshx` 显式自举；**ci.yml 补 editable 安装**（裸 pytest
  陷阱：cwd 不进 sys.path，删掉逐文件引导后 CI 必挂——W1 自带配套件）
- 代理自伤三处全被自检网抓获（CRLF 模板哑火 / 43 文件孤儿 import tokenize 排查 /
  混合行尾文件缩进 import 漏改）——"强制收尾 grep"规则证明了自身价值
- 白名单残留三件有据；**已知余量 design/ 15 文件**（不在委托白名单，代理守规未扩权，
  垫片保绿）→ W_final 收
- 门证据：套件 **1275+4skip（18:45）/ 10 绿** + **GOLDEN: PASS (bit-identical)**（判定行
  核实——iter43 的 PS 假红教训已内化为"golden 步尾 exit 0 + 只认判定行"流程）
- 下一步：W2 = validation/ 17 + df_surrogate/ 7 迁移（同 §10 委托模式）

## iter 43 · 2026-07-21 · P1.8b W0 身份垫片 ✅——**双风格同对象，迁移从此顺序无关**（`88b63e9`）

- Alex 拍板"启动 P1.8b"。W0 = openspec 三件套 + 身份垫片 + venv editable
- **垫片核心**：新建 `sjtu_tpmshx/__init__.py`（原 namespace 包）——自举 + 前插
  meta-path finder，`sjtu_tpmshx.X` 与顶层 `X` 解析为同一模块对象 ⇒ 双风格混用
  无法再产生双状态（warn 注册表/logutil logger/缓存），W1..Wn 任意顺序任意粒度安全
- 实现抓到两个 CPython 实测坑：① reload 后类对象换新使 isinstance 判重失效 → finder
  装双份（改类属性标记判重）；② import 机制在 create/exec 之间把被别名模块的
  `__spec__` 改绑为包名 spec（`reload(solvers)` 会静默降级 no-op）→ exec_module 恢复
- 身份测试 7/7；editable 后**包外任意 cwd 也拿到同一对象**（新能力）；pip check 净
- **门史（一红一假红，均已记档）**：首轮红 = mypy "found twice"（新 __init__ 使上溯
  出双模块名，静态世界的双风格问题）→ `explicit_package_bases = true`（cwd 基底位同
  语义）；重跑套件绿但 golden 步骤路径误写 validation/（正确 runs/_out/）→ 单步补跑
  **PASS 位同**；补跑 exit 1 系 **PS 5.1 stderr 包装假红**（求解器日志走 stderr 被
  2>&1 包成 ErrorRecord），以判定行为准——环境备忘新坑
- 门证据：套件 **1275+4skip（18:57）/ 10 绿**（+7 = 身份测试）+ golden **位同 PASS**
- 下一步：W1 tests/ 73 文件迁移（§10 委托子代理 + 复核）

## iter 42 · 2026-07-21 · P1.3/P1.5 关账 ✅——**前提修正：#4 早已落地，零代码**（docs-only）

- Alex 批准原建议（"补做 #4 警告注册表 + 关账"），开工核实即推翻前提：**#4 已于
  iter 8（`7cbeee1`）随 P1.3-A 落地**——qnehvi `_reset_warn_registries()` 战役入口调用，
  测试 `test_qnehvi_campaign_resets_warn_registries` 钉住粒度决策（per-campaign：
  500 评估战役内仍去重，镜像 ComputePipeline.run；per-design 反而会刷屏）
- 循环误报根因：iter 41 答疑时只 grep 两个评估器文件本身，漏了上一层 qnehvi 战役
  入口——**"评估器入口"字面被 iter 8 有意收窄为"战役入口"且有测试背书**，本轮核实
  qnehvi 为评估器唯一批量调用方（一次性脚本=新进程，注册表无陈旧态），收窄成立
- 关账：P1.3 勾选（四子项决议映射：①iter 8 ②iter 9+D2(c) ③iter 41 D3(c) ④iter 8
  战役级）；P1.5 勾选（数据类化 ✓ P2.0，文件级迁移归 P1.8b，无独立余量）；
  Phase 1 头部余留注记改为"仅 P1.8b 波次"
- 验证：docs-only（ROADMAP/STATE/PROGRESS/progress.html），零代码零门，免套件有据
- 下一步：回待命。P1 真余量收敛为 P1.8b 一项，与 Phase 5 候选池 A2/B/C/D 同级待拍板

## iter 41 · 2026-07-20 · D2(c)+D3(c) 执行 ✅——**双前提修正、零重基准**（`20031ba`）

- Alex 拍板（"可以，按你的建议开始吧"）：D2=(c) 现状+文档化、D3=(c) 分维一致先行 +
  (a) 立为候选 A2。本轮执行两条已决
- **前提修正 ①（D3）**：背景里"2D uniform 亏 7.38%"是 **1D 种子算术假象**——2D 捕获回退
  发生在压力场建立之前（simple_solver.py solve() 头注），捕获值=构造密度=ρ(T_in,P_in)，
  评估器一直钉的就是物理 G。实测冻结两元组**位同零移动**（+0.00% 全项），预备的 §5
  重基准未动用 ⇒ 改动性质=语义加固（防未来重建/复用模式漂移），非数值修复
- **前提修正 ②（D2）**：背景里"2D 管线从未有过 choke 守卫"失实——solve_2d 自 2026-06-25
  起有解后可压有效性门（与 3D 同款三档）；真正无解后门的只有 2D 评估器，(c) 更稳
- 改动：evaluator.py 双侧补显式 `rho_inlet_ref=ρ(T_in,P_in)`；绊线契约更名
  post_d3c 并新增 4 断言守候选 A2 之门（3D 评估器/求解器禁长旋钮）；DECISIONS D2/D3
  回写"执行+前提修正"；atlas optimization 卷收编
- 3D 侧刻意不动：19.30% 出口基准 G 亏空**真实成立**（首次真解后捕获，机理与 2D 不同），
  候选 A2 立项理由不变
- 门证据：套件 **1268+4skip（12:45）/ 10 绿** + golden **位同 PASS**（日志 upgrade/logs/iter41-*）；
  契约 6/6 绿；ruff 绿。吸收 tick ×3（跑门期间）
- 下一步：回待命模式（候选 A2/B/C/D 待 Alex 拍板启动）

## iter 40 · 2026-07-20 · 收尾轮 ✅——**ROADMAP 全清，循环转待命**

- 终审认证门（HEAD 含全部 82 提交）：**1268+4skip / 10 绿（10:40）+ golden 位同**——
  分支盖"可合并"戳，日志 upgrade/logs/final-*
- `upgrade/FINAL-REPORT.md`：一页摘要（七大交付表）、合并指南（本地 master 未动可快进；
  远端核对流程；CI 首跑预期；upgrade/ 目录三选一处置建议 a 原样合入）、
  D2/D3 + Phase 5 四池选单（规模/风险/依赖注记）、开放项六条、待命模式说明
- 待命模式启动：tick 只查新 `已决` 与 STATE next 改写，无事静默；定时器照常 §8 维护
- **循环全程战报**：40 轮 / 两日 / 29 正式条目 + 2 插单全清；零红灯、零重基准、
  golden 全程位同；套件 +23 至 1268；四常驻门；真雷 6 处修复；4 次证据确凿的
  零改动裁决；2 次前提坍塌纠正（DRIFT.md/死代码）；D1 已决执行、D2/D3 备齐待拍板

## iter 39 · 2026-07-20 · P4.4 HANDOFF 刷新 ✅（`312ac37`）——**Phase 4 收官，主线全绿**

- 体例裁决：HANDOFF 是 07-11 的**证据快照**（问答体+证据分级），改写原文会毁证据链——
  改为文首挂 16 行"状态总更新表"（问题→现状→证据 commit）+ §1/§2/§3 三节结论行内戳
- 对账结果：§1 上游已修（P1.2）、§2 已解（aa3f477+P1.3 双层）、§3 契约已立且分歧升 D3、
  §8a/§9a/§9b 已解（data-repo.pin/golden 入库/锁 83 包）、§9c 被锁文件取代、
  §5 部分超越（**本循环即 Server 2022 实跑证据**：1268 绿 × 数十轮）、§6 部分解
  （BLAS 时序缺陷留 Phase 5 候选 C）、§10 过时（atlas 已入 master）、§4/§7 仍开放
- AGENTS.md 尾巴收案：基点树 git 历史均无此文件（当年开发机未跟踪文件），无可修对象
- **Phase 0–4 主线全部完成**（iter 1–39，39 轮：P0 安全网 5 项、P1 架构 9 项、
  P2 质量 8 项、P3 性能 3 项、P4 文档 4 项 + 中途插单进度页/候选池）
- 下一步：收尾轮（合并前清单 + Phase 5 选单 + 终审报告）

## iter 38 · 2026-07-20 · P4.3 CI 增强 ✅（`f6b6a5a`）——评估变抓虫

- **发现真缺陷**：test_lint_gate/test_type_gate 是无 skip 守卫的 subprocess 调用（有意——
  门不许静默消失），而现行 ci.yml 不装 ruff/mypy → **分支合并 master 后 CI 必红**。
  这把 P4.3 从"可选增强评估"升格为"必修"
- 修复即增强：install 行 +ruff+mypy（CI 从此真执法 lint/type/layering 三静态门）；
  选择表达式 `not slow` → `not slow and not heavy`（剔 21 个最重 3D 积分测试——CI 定位
  smoke/静态层，物理回归归本地全量门，ULP 钉定 CI=true 本就跳过）
- 验证：manifest nodeid 平台中立性核过（conftest basename 归一）；slow∩heavy 重叠恰 3 文件；
  本地收集 1223/1282（59 反选）、三门测试在子集内。**改动只入库不推送**（红线），
  Alex 合并后 CI 生效
- 插曲：轮中 Alex 暂停 loop（定时器 ef9566f6 删除），恢复时重建为 c87569d6；
  半截工作树跨暂停无损收尾
- 下一步：P4.4 HANDOFF 刷新（Phase 4 最后一项）

## iter 37 · 2026-07-20 · P4.2 数字口径复核 ✅（`978c066`）+ §8 定时器重建

- **复核结论：headline 数字零漂移**——README/PROJECT_MANUAL 的 1.73/≈10/≈3/4.88/2.12/
  8.62/2.49/p_obs≥2.07 全部与 BASELINE.md 实测一致；V&V 叙事自洽（"≈5.3%"是标注清楚的
  旧 runner 门网格历史值；4.93→4.88 等链条均为带日期的沿革记录）。ROADMAP 立项时担忧的
  "1.71/1.73 类问题"不存在
- 真正过时的两处已修：Tested-on 增 **Windows Server 2022**（128 核 EPYC 2026-07 全套
  复验证）；README/手册测试命令区增服务器双跑脚本 + 56s 快档指引（-n auto 128 核卡死
  陷阱从 atlas 提升到用户文档）
- **§8 定时器重建**：d7888157（07-19 布防）→ **ef9566f6**（07-20 重建，spec 不变
  `7,22,37,52 * * * *`），armed_at 更新，下个重建窗口 07-25 前
- 下一步：P4.4（HANDOFF 刷新）——P4.3 CI 评估轮先行

## iter 36 · 2026-07-20 · P4.1c 外围域收编 ✅（`006e99f`+README 补丁）——**P4.1 整项收案**

- ui-core：13→14 mixin（MRO 全列更新）、run_controller 912+run_results 328、write_result
  迁址、行号影响边界（≤350 安全）；收编节含 iter 28 依赖测绘结论与 except 政策
- runs：**"唯一被 UI import 的例外"条目消除**（polygon_calc 迁 ui/）、根目录 14→13、
  tools 5→8（审计/manifest/缝手术三件入册，缝手术标注"一次性工具留档"）
- solvers-2d：threads 52→102 + P3.2 机制全记（含 caplog/tpmshx. 前缀陷阱）；
  solvers-closures：chi_s "导入时读取一次"**过时断言改正**（P1.6 每调用读）+
  geometry 缓存拷贝语义（W7b 防御两件）收编节
- PROJECT_MANUAL §6 节首挂 07-20 增量索引（8 组新增/迁移一句话 + cli.py 与 design/cli.py
  撞名辨析，细节指向 atlas）；atlas README 收案状态 + 摘要区两处回声修正
- 工艺教训：heredoc 传中文 python 脚本再遇 GBK 损坏——改走 Write 工具落盘执行（稳定复现
  的环境约束，已是第二次踩，此后一律 Write+执行）
- **P4.1 战果**：10 卷收编、7 卷盘点判定无分支级失准；三轮 docs-only 全程零代码风险
- 下一步：P4.2 README 数字口径复核

## iter 35 · 2026-07-20 · P4.1b atlas 架构域收编 ✅（`0fad954`，docs-only）

- pipelines.md：run_stack_3d 重组入册的关键决策——**不逐行重标定**（2107→3001 行全漂移），
  改为 ⚠ 头注声明 + 编排链新行号（:586/:1106/:2128/:1339/:1627/:2975）+ 旧行号段→新函数
  归属映射表；"逻辑逐字节未动（golden 位同护航）"是给读者的定心锚
- controllers.md：PEP 562 惰性（cli 零 Qt 的关键一环）、pipeline_for 有了首个生产消费方、
  P2.5a 行号影响面（≤350 不受影响的精确边界）
- core-domain.md：evaluators 433→639 新结构（:46 envelope 导入/:59 R_AIR 再导出/
  :66 后解门/:145 evaluate_3d）；D3 绊线与契约测试入册
- optimization.md：P3.3 重写"BO 内层线程"段；**诚实注记**：本卷 07-12 审计指出的
  parallel_runner BLAS 钳制时序缺陷分支未修（与 numba 主热点不相干，留 Phase 5 候选）
- 下一步：P4.1c 外围域（ui-core/runs/solvers 小修/PROJECT_MANUAL §6），P4.1 收案

## iter 34 · 2026-07-20 · P4.1a atlas 基建域收编 ✅（`433eb2b`，docs-only）

- tests.md 六处失准就地改正：文件数 151→162、marker 两→三（+heavy）、conftest 两→三件
  副作用、`-n auto loadscope`+"≈1037" → 双跑脚本+1268+10 现况、"精读 151"回声；
  文末收编节：五常驻门/fast-tier 机制/golden 入库(D1)/双脚本/计数沿革
- repo-infra.md 五处改正含一处**原生错误**（threads 包路径笔误 df_surrogate→solvers，
  非漂移是笔误）+"未发现 pyproject"过时断言；文件表 +7 行；收编节：打包地基/CLI/
  质量门四件套/锁 83 包/环境变量新增/upgrade 目录
- 打法定型：失准处就地改正标 ⟨07-20 更新⟩（保考古线索），结构性新增进文末收编节；
  atlas README 加滚动收编状态行
- 下一步：P4.1b 架构域四卷

## iter 33 · 2026-07-20 · P4.1 atlas 盘点 ✅（docs-only，前提修正）——Phase 4 开张

- **前提坍塌（第二例，处置同 P2.3）**：ROADMAP 所称 DRIFT.md 全库不存在——播种时臆想
  产物，漂移只活在提交信息/PROGRESS 里。章程修正：不造间接层，直接写回卷
- 盘点：分支 vs 基点 4b32da4 共 164 文件变更；结构性漂移 = 新文件 15（pyproject/cli/
  _version/run_results/五守卫测试/三工具/双脚本等）+ 结构性改动（run_stack_3d 拆分、
  controllers 惰性、evaluators 权威、threads advisory、geometry 拷贝语义）
- 受影响卷映射（合计 3571 行，可控）：三域三轮——P4.1a 基建（repo-infra/tests/README）、
  P4.1b 架构（pipelines/controllers/core-domain/optimization）、P4.1c 外围
  （ui-core/runs/solvers 小修/PROJECT_MANUAL §6）；HANDOFF 单列 P4.4
- 下一步：P4.1a

## iter 32 · 2026-07-20 · P3.3 BO 核预算 ✅（`e233460`）——**Phase 3 收官**

- _resolve_core_budget 提取：钳制 [1, cpu_count] + 来源标签四态；并行启动一行 INFO
  （workers × inner × 预算来源）——多臂并发（port_retest 四臂类）从此可审计
- 默认/合法路径行为逐字节不变；唯一语义变化 = 超机预算钳制（堵 07-11 超订 bug 残留口）；
  env 索引补录 TPMSHX_BO_CORE_BUDGET（此前缺失）
- 测试 +7（解析矩阵全分支，helpers 19 绿）；门禁 1268+4skip / 10 绿（10:45）、golden 位同
- **Phase 3 完**（fast-tier 20×、线程建议、BO 预算——三项全数落地，iter 30–32 三轮）
- 下一步：P4.1 atlas 漂移收编（先盘点 DRIFT 存量 + 升级分支自身新漂移）

## iter 31 · 2026-07-20 · P3.2 线程建议 ✅（`547b7d0`）

- recommend_solver_threads（min(64, 逻辑核/2, 池上限)；本机 64/128）+ warn_if_default_pool
  一次性建议，挂 simple_solver_3d 并行分派真分支；三静默分支（env 已设/GUI 已调低/小机器）
- 设计约束写死：**绝不自动改池**——prange 归约序变更位移且生产网格无 golden 覆盖，
  advisory-only；不变量护栏两审零物理接触
- 测试 +3（1258→1261）；教训入档：logutil 挂 `tpmshx.` 前缀根且 propagate=False，
  caplog 失明 → 直挂模块 logger；快档 dogfood 首战 45s 抓获开发中真失败
- 门禁：1261+4skip / 10 绿（10:32，空载快跑）、golden 位同
- 下一步：P3.3 BO 预算 ergonomics（先现场核实）

## iter 30 · 2026-07-20 · P3.1 fast-tier ✅（`53431bb`）——Phase 3 开张

- census 轮（--durations=0 镜像服务器环境，双 pass）：265 计时测点 / 4620s 计算量；
  阈值扫描 300/120/60/30/20/10/5s 全表——**30s 档最优**：21 测试（1.7%）承载 89% 计算量，
  heavy 全是 3D 积分测试（conservation/partial_bc_ghost_b/asym_porosity 等 6 模块）
- 机制（零测试文件改动）：manifest 入库（生成器可重生）→ conftest 收集期动态 heavy 标
  （basename 归一，调用目录无关）→ run_tests_fast.ps1 排除；反选精确 21
- 实测 **56s vs 19min（20×）**：1237+4skip 46.5s + 串行模块 8.8s，全绿
- 红线三处写死（脚本/marker 文案/manifest 头注）：快档绿 ≠ 过门；slow 语义未碰
- 门禁：双 pass 1258+4skip / 10 绿（18:47）、golden 位同
- 下一步：P3.2 线程默认值

## iter 29 · 2026-07-20 · P2.5a run_controller 单刀 ✅（`86b12e4`）——**Phase 2 收官**

- 五方法（write_result/_finalize_plots/_update_result_summary/_diag_summary_text/
  _show_diag_dialog）逐字节搬至新 RunResultsMixin（AST 比对 HEAD 五方法体位同）；
  run_controller 1215→912 行，头注清单 18→13 并注明去向；MRO 插位紧随 RunController
- 冒烟：五方法经 Main_Menu MRO 全解析至新 mixin、旧 mixin 不再定义；ruff 绿；
  唯一模块级依赖 TOAST_MS_SHORT 随迁
- 门禁：双 pass 1258+4skip / 10 绿（19:03）、golden 位同、直击三测试
  （finalize_3d_result_sync/orch_finished_3d_state/run_controller_preflight）绿
- 轮中插曲（用户请求，两个独立 docs 提交）：进度页 render_progress.py + progress.html
  入库（d7c948b，PROTOCOL §9 增每轮重渲）；Phase 5 候选池立项（f8b06d9，Alex 批准，
  三池选单，候选不计完成度）
- **Phase 2 全线完成**（P2.0 数据类化 / P2.1+b+c lint 三波 / P2.2 类型门 / P2.3 死代码 /
  P2.4 异常日志 / P2.5 GUI 减脂——iter 21–29，其中四轮为证据确凿的零改动裁决）
- 下一步：P3.1 fast-tier（先取 --durations 数据）

## iter 28 · 2026-07-20 · P2.5 首轮：mixin 依赖测绘 ✅（docs-only，章程收窄）

- AST 交叉引用矩阵（14 文件：13 mixin + main）：**耦合低，架构判定健康**——多数 mixin
  依赖 0–3 个同伴，zone_panel/io_actions 零 fan-in，枢纽 shortcuts(用7)/session_presets(用6)/
  main(用7)。原设想"13-mixin 是巨物问题"被证据推翻：mixin 分层本身是合理的责任划分
- 真靶标唯 run_controller 1215 行（20 方法），四责任区测绘：启动/预检 35–350、
  orch 信号处理 495–801（_on_orch_finished 528–716 独占 188 行）、结果呈现 351–494+1003–1165、
  计算 UI 状态 802–1002+1166–1215。保护面 3 直击测试 + 17 Qt 测试，无 golden
- 章程裁决：**只切一刀**（P2.5a 结果呈现区 → run_results.py，1215→~845）；ui 273 except
  存量不动（churn 风险>>收益），新代码 logutil——政策一行即收，不立扫改波次
- 下一步：P2.5a 执行（Fable 直做——方法搬移涉 MRO/keep-alive 判断，不派机械子代理）

## iter 27 · 2026-07-20 · P2.4 异常/日志策略 ✅（盘点轮，docs-only，零批次）

- 人口普查：0 裸 except；400 处 except Exception（ui 独占 273 = 68%）；库内 print 144
- 核心三目录 28 处逐站分类：全为存证故意——发现 **2026-07-03 已做过一轮 except-audit**
  （sigmoid_field/flux_3d 留有审计注释，静默 fallback 当时已放响）；余为 warmup 尽力型（注释在）、
  CoolProp 能力探测、线程 err[i] 捕获后重浮、UI 回调护栏（吞对：坏回调不该杀数值解）、
  traceback 打响型。无 P0.3 族潜伏故障
- print 双层复核：95/144 在 __main__ 区；分类探针"活路径 49 处"系统性高估——逐函数核查
  全在 _self_test()/main()/demo（residual_correction 13 处全在 _self_test:263、
  surrogate_v3 11 处全在 main:619、predict 2 处在演示函数、parallel_runner 1 处是 CLI 输出）。
  **活求解路径 print = 0**
- 处置：ui 273 处移交 P2.5 章程（GUI 域政策，随减脂就地办）；无独立代码批次立项——
  连续第三轮"零改动"裁决，佐证历史审计（06-16 死代码、07-03 except、P0.3、P2.1/b）
  已把卫生欠账付清，Phase 2 剩余价值集中在 P2.5
- 下一步：P2.5 首轮（mixin 依赖测绘）

## iter 26 · 2026-07-20 · P2.3 死代码处置 ✅（盘点轮，docs-only，零处置）

- 命名靶标现场核实全部"活"：zone_config（104 引用/17 文件，ZoneInputConfig 是 2D 计算路径
  活数据结构）、zone_table（87 引用/8 文件，UI Define-zones 全套）——头注"DEPRECATED for
  optimizer use"语义准确，无需动；runs/archive frozen 声明 P1.7 已备
- 全库孤儿扫描（自写只读探针，165 库模块）：16 未导入者中 13 为入口脚本（正常），
  3 个模块嫌疑逐一复核全为**相对导入误报**（探针正则不识 `from .X import`）：
  _kernels_ltne_3d(1178 行) ← ltne_energy_3d:322；builders_sidebar ← builders_canvas:19；
  skeleton ← builders_canvas:1079（函数内惰性导入）。**0 真孤儿，0 删除候选，未立 D 条目**
- 方法论记录：未来孤儿检查挂 audit_import_graph 的真导入图做（正确处理相对/惰性导入），
  正则探针只配当一次性初筛；细粒度死代码（死名/死导入）已由 ruff F 门持续执法
- 下一步：P2.4 异常与日志策略（先盘点分类）

## iter 25 · 2026-07-20 · P2.1c ruff format 评估 ✅（纯评估轮，docs-only）

- **裁决：不做全库 format（本分支阶段性关闭）**。全部探测只读（--check/--diff），零代码改动
- 硬证据：①`ruff format` 影响 359/370 文件、3214 hunk、−20517/+38878 行（包总 87369 行，
  ~45% 搅动）；②atlas file:line 引用 2355 处 / 376 个唯一文件路径，全面腐蚀；③12 个测试文件
  读源码断言，23 处 quoted marker 中 ≥3 处引号敏感（`e_info.get('converged'`、
  `cfg.get('outer_anderson', False)`、`'p_clip_hits'`——format 把 ' 翻成 " 即断）+
  长表达式 marker（`_ALPHA_T * rho_new + ...`）有反流断裂风险；④调参救不回：
  quote-style=single + line-length=200 仍 360 文件重排（搅动源自缩进/空格/尾逗号归一）
- 附带成本盘点：git blame 断代（ledger/报告溯源链依赖 file:line 考古）；numba 磁盘缓存
  一次性全失效（无害）；merge-to-master diff 被排版噪声淹没（升级分支"每个 diff 可审"承诺破）
- 未来重启三前置（写入 ROADMAP 条目）：atlas 锚点化或同波重基线；marker 全改 AST/标识符级；
  master 合并后独立 format-only 提交 + .git-blame-ignore-revs
- 下一步：P2.3 死代码处置（先盘点，删除项过 DECISIONS-NEEDED）

## iter 24 · 2026-07-20 · P2.2 mypy 核心面门 ✅（`464076d`）

- 宽松档 [tool.mypy] + 七文件核心面清单（envelope/compute_pipeline/domain 配置结果/
  configs/_version/cli）清零：compute_config 3 处注解性修正（异构 dict 先声明后分支赋值、
  gate-check 循环变量改名破类型合一、补 Tuple 导入）+ cli warnings_list 收窄——零物理默认值变动
- test_type_gate 常驻（subprocess mypy @清单，cwd=包目录与顶层导入约定一致）；check.md §2a2 入册；
  锁文件 80→83 包（ruff/mypy 入锁）
- 门禁：suite 1258+10 绿 / 4 skip（19:06，负载偏高段）、golden 3D 位同、
  mypy "Success: no issues found in 7 source files"
- 流程：开工首个 Edit 即 STATE 标记（iter 23 教训，本轮已守）；轮中撞 /compact 一次，
  后台门任务跨压缩存活、凭 task 通知收轮
- 勘误：iter 22/23（及 pyproject 内 P2.1/P2.2 溯源注释）曾误记日期 2026-07-21，git 时间戳
  实为 07-20——PROGRESS 本轮已改；pyproject 注释留待下次正当编辑该文件时顺手改（避免
  纯注释改动空耗一轮套件）
- 下一步：P2.1c ruff format 评估（纯评估轮）

## iter 23 · 2026-07-20 · P2.1b F841 清偿 ✅（`581e790`）＊日期按 git 时间戳修正（原误记 07-21）

- 52 处初判 + 5 处级联全清（净 −46 行）：死解包/死拉取/jit 内核死载入（A/B 侧 ef ×4，
  golden 位同护航）/标量旧方案遗骸（T_avgA/B）/整死 if-else（stages_2d 行均孔隙率）/
  U_sf 超表速度残迹；Qt keep-alive 语义保全（app→_app）、副作用调用去名留调
- pyproject 移除 F841 ignore——**全量执法开启**；批量手术脚本逐行断言护航零失配
- 流程小疵自纠：开工漏写 in_progress 标记（连续第二次，iter 8 后再犯）——收尾时发现，
  下轮起开工首个 Edit 必须是 STATE 标记
- 门禁：suite 1257+10 绿、golden 位同
- 下一步：P2.2 类型注解

## iter 22 · 2026-07-20 · P2.1 ruff lint 门 ✅（`121413d` 机械 + `6e65487` 语义）＊日期按 git 时间戳修正（原误记 07-21）

- 352 发现 → 0：238 自动修 + 7 F821 逐案（**三真雷**：Save Preset 即崩的缺导入、
  pin 分支未定义变量、直跑块引用已亡测试）+ F841 缓议 P2.1b + format 单列 P2.1c
- 两次红灯全是仓库防御工事的胜利：tests/design 收集崩抓住 tpms_calc 门面被删、
  test_pipeline_reexports 锁面测试抓住 stages_2d——门面豁免清单由实证驱动补齐；
  41 文件被删名属性引用全扫零受害
- lint 门常驻 + /check §2a + 锁刷新（81 包，指纹 0e079835f744709…完整值此处存档）
- 门禁：suite 1257+10 绿（第三跑）、golden 位同
- 下一步：P2.1b F841 人审

## iter 21 · 2026-07-20/21 · P2.0 数据类化 ✅（`d0238e6`）—— **§10 委托首战**

- Sonnet 子代理执行（80/6/22/25 字段四数据类 + 五签名坍缩 + 解包块；自带 AST 交叉核验），
  Fable 复核（diff 定点审：残差全在允许模式内、零函数体泄漏）+ 门禁 + 签发
- 委托模式验证成功：规格逐名指定 + 禁改函数体 + 禁跑套件禁提交 → 执行方零歧义返工
- 门禁：suite 1256+10 绿、golden 位同 ×2；文件级迁移并入 P1.8b
- 下一步：P2.1 ruff（继续委托模式）

## iter 20 · 2026-07-20 · P1.9 分层裁决 ✅（`c43c7db`）—— **Phase 1 主线收官**

- 两修：polygon_calc（Qt 耦合 UI 代码）迁回 ui/；__version__ 抽 _version.py 叶子
  （ui→main 环消除，pyproject 转 dynamic 版本单源）
- 两裁：solvers↔df_surrogate 闭合边界互依对、domain→_domain 叶子常量——SANCTIONED
  清单内置工具（附理由），报告单列
- 层级门常驻：test_import_layering 进套件、/check §2b；**VIOLATIONS = 0**
- 门禁：suite 1256+10 绿、golden 位同；19 分钟套件尖峰确认为瞬时负载（本轮回落 10:31）
- **Phase 1 战报（iter 6-20）**：审计 → 验证收案 ×1 → envelope 权威+门 ×2 切片 →
  契约测试 → 五缝拆解（1955→156）→ 缓存卫生 → 死路径 → 打包 → 分层裁决；
  全程 golden 位同、零带病提交；待决 D2/D3 不阻塞
- 下一步：Phase 2 开工，P2.0 = §10 委托首战

## iter 19 · 2026-07-20 · P1.8 打包地基 ✅（`827bee9`）

- pyproject（extras 分组、包数据、诚实的 P1.8b 注记）+ tpmshx-run headless CLI
  （--dry-run 实测 Pipeline2D）+ controllers PEP 562 惰性导出（接缝零 Qt 实证）
- 一次性 venv editable 安装冒烟全过；**工作 venv 未动**（循环环境稳定优先）
- P1.8b 立项（导入风格全库迁移 + 引导分波删除 + venv 转 editable——§10 委托候选）
- 门禁：suite 1255+10 绿、golden 位同
- 下一步：P1.9 分层违规裁决（P1 收官项）

## iter 18 · 2026-07-20 · P1.7 死路径清理 ✅（`dd598d9`）

- smooth_df rebuild 死路径：显式 FileNotFoundError 守卫（溯源+修法）+ env 覆盖口
- 4 工具脚本 Desktop/D:\ → env 覆盖 + runs/_out 默认；vault 输入指向现实布局
- archive/ 增补"死路径故意不改"证据链声明（尊重既有 frozen README）
- 门禁：suite 1255+10 绿、golden 位同。注意：全量套件连续三轮 ~19 分钟
  （高负载 or 用例增长），P3.1 fast-tier 优先级↑
- 下一步：P1.8 pyproject 打包（P1 尾声）

## iter 17 · 2026-07-20 · P1.6 缓存与 env 卫生 ✅（`7d70227`）

- 两个 W7b 潜伏炸弹拆除：compute_geometry 共享 dict → 浅拷贝入口；_phi_grid 共享
  ndarray → writeable=False（写入即炸）
- TPMSHX_CHI_S 改 per-call（import 冻结的 K_ss reload 隐患）；AMG 缓存补 reset 钩子
- +5 守卫测试；chi_s 优先级测试从"patch 模块全局"改为 setenv——旧写法正是冻结
  逼出的变通，佐证修复价值
- P1.5 收尾评估定案：五缝判完成；数据类化+文件迁移降为 **P2.0**（首个 §10 委托候选）
- 门禁：suite 1255+10 绿（重跑全量）、golden 位同；invariant-guard 钩子首次触发（合规）
- 下一步：P1.7 死路径清理

## iter 16 · 2026-07-20 · P1.5 C 缝 ✅（`2549a79`）—— **五缝收官**

- 最难一缝的解法："整块搬移"（状态初始化+闭包+驱动 730 行同走）让 nonlocal 域内自洽，
  预想的"显式耦合态对象"根本不需要
- nonlocal 重绑名（Ta/Tb/Ts/chi_B/h_v 场/K_ffB）= **in-out 双身份**：初值形参进、终值 bundle 出
  ——工具为此补最后两刀（条件 import 首现、nonlocal 输入合成），全程 golden 当场纠错
- **_run_3d_stack：1955 → 156 行**（build→hv→outer→extract→verdict 纯编排）；
  又一个源码断言随迁（test_outer_anderson）
- 门禁：suite 1250+10 绿（重跑全量）、golden 位同 ×2
- 五缝总账（iter 12-16）：五段共 ~1930 行逐字节搬移，零行为漂移（每步 golden 位同），
  工具从朴素块搬移进化出七项静态分析能力，全程由门禁当场纠错、零带病提交

## iter 15 · 2026-07-20 · P1.5 E 缝 ✅（`694e5fa`）——工具毕业考

- 裁决尾段（401 行）→ `_assemble_3d_verdict`（81 输入 → _result；return 留守）
- 工具连修三个静态分析盲区（每个都由 golden/运行时当场揪出，零带病提交）：
  AugAssign 隐式 load、先读后绑 in-out（顺序敏感首现）、嵌套推导式作用域（抑制集穿线）；
  Nonlocal 自由变量支持顺手装上（C 缝前置）
- _run_3d_stack **1955 → ~750 行**；门禁 suite 1250+10 绿、golden 位同 ×2
- 下一步：P1.5 C 缝（最难的外循环闭包，8 nonlocal）

## iter 14 · 2026-07-20 · P1.5 D 缝 ✅（`b6ce215`）

- 指标/场提取段（202 行）→ `_extract_3d_metrics`（36 输入 → 25 名 bundle），
  工具一次成型（成熟度可见：零试错 apply）
- _run_3d_stack ~1150 行；门禁 suite 1250+10 绿、golden 位同 ×2
- 下一步：P1.5 E 缝（裁决+组装尾段），随后只剩最难的 C 缝

## iter 13 · 2026-07-20 · P1.5 B 缝 ✅（`ddf9c64`）

- h_v 机械群（5 闭包 + 初始场，186 行）→ `_build_hv_machinery` 工厂（23 显式输入，
  闭包捕获工厂形参；6 名 bundle 含跨缝可调用 _build_hv_local_3d）
- 工具两级进化并回同步：作用域感知（闭包内 return/形参不误计）+ 嵌套 def/lambda
  形参归位（A0/Dh 泄漏）——试运行两轮迭代出正确输入集才 apply
- _run_3d_stack ~1350 行；门禁 suite 1250+10 绿、golden 位同 ×2
- 下一步：P1.5 D 缝（指标/场提取，近纯函数段）

## iter 12 · 2026-07-20 · P1.5 A 缝 ✅（`9fcdbcc`）

- 415 行 setup/build 段**零手抄**抽出为 `_build_3d_problem(cfg)`（AST 名字流算 80 名状态包，
  文本手术逐字节搬移，收发元组同名单生成）；_run_3d_stack 1955→~1540 行
- 两次现场教训：①条件绑定名（19 个）触发 UnboundLocalError——工具加定赋值分析一次修全；
  ②一个源码标记 wiring 测试随迁（断言意图不变，指向新家）
- 手术工具入库 runs/tools/seam_surgery_3d.py，B/D/E 缝改常量复用
- 门禁：suite 1250+10 绿 / 0 败（重跑全量）、golden 位同 ×2
- 下一步：P1.5 B 缝（h_v 闭包群提升）

## iter 11 · 2026-07-20 · P1.4 契约测试 ✅（`6c727dc`）

- 六条评估器↔管线有意差异 → 机器断言（legacy 默认 / B 冻结 / 整形隔离 / 不路由 /
  2D choke 双向现状 / **D3 绊线**——rho_inlet_ref 四处在缺席断言，决议必触发）
- 主规则入档：Pareto 选点须经 Pipeline 复核；处置规则：绝不删断言了事
- 途中修正一次自己的断言（choke 词汇出现在管线注释里——改为 raise 语义断言）
- 门禁：suite 1250+10 绿 / 0 败（+6 契约测试）
- 下一步：P1.5 run_stack_3d 五缝拆分（A 缝先行）

## iter 10 · 2026-07-20 · P1.3 切片 C → **调查升级为 D3**（docs-only，无码）

- 现场核实推翻切片前提：不是"评估器缺参数"，是 **2D/3D 管线自身 G 口径不一致**——
  2D 显式钉物理 ρ(T_in,P_in)·u；3D 求解器根本没有 rho_inlet_ref 旋钮，首解捕获
  ρ(T_in,P_out_seed)，且评估器与自己的 choke 种子自相矛盾
- 量化（1D 种子，冻结测试点）：2D 亏 **7.38%**、3D 亏 **19.30%**；validate 用 ρ(T_in,P_in)
  换算实验 ṁ ⇒ 3D 管线系统性低于实验吞吐，偏差已被 γ_df 锚定部分吸收（标定纠缠）
- **D3 登记**（选项 a 全线物理 G / b 现状 / c 分维一致过渡；建议 c 先行 + a 立项调查）；
  P1.3-C 标 BLOCKED；openspec D4、审计报告 §2 同步修正
- 教训沉淀：连续第三轮"现场核实改写条目"（P1.2 已修、P1.3-B 范围、P1.3-C 升级）——
  协议 §1-2a 这步的价值已自证
- 下一步：P1.4 evaluator 契约测试（G 口径差异记"待决 D3"，不锁方向）

## iter 9 · 2026-07-20 · P1.3 切片 B ✅（`2ea1d37`）

- 3D 评估器 post-solve envelope 门上线：与生产管线同判据（压力地板 + 逐格 Mach），
  失败走既有 NaN+invalid → BO 罚值通道，零新语义
- **范围修正**：2D 管线自身无 post-solve 门（ledger O1）——2D 侧要不要引入是物理政策，
  登记 **DECISIONS D2**（循环建议 c 维持现状），不替 Alex 决定
- 假求解器单元测试 ×3 + wiring（8/8）；期间修了一处测试断言字符串错误（supersonic ≠ Mach）
- 门禁：suite 1244+10 绿 / 0 败、golden 位同、frozen-values 未动（健康工况零影响实证）
- 下一步：P1.3 切片 C（rho_inlet_ref）——第一个预期动数字的切片，§5 重基准流程伺候

## iter 8 · 2026-07-19/20 · P1.3 切片 A ✅（`7cbeee1`）

- 三处手抄 1D D-F 种子代数收归 `envelope.predict_outlet_p_sq`（位同：同式同序同常数 +
  frozen-values rel=1e-12 未动实证）；R_AIR 改权威别名
- BO 战役入口重置 extrap/choke 警告注册表（每战役粒度，设计理由记 openspec D2）
- openspec 变更 evaluator-envelope-authority 落档（切片 B/C 设计已定：post-solve 门复用
  罚值通道不 raise；rho_inlet_ref 预期动数字走 §5）
- 门禁：suite 1240+10 绿 / 0 败（+4 新守卫）、golden 位同
- 下一步：P1.3 切片 B（post-solve 门）

## iter 7 · 2026-07-19 · P1.2 验证收案 ✅（docs-only）

- **现场核实推翻条目前提**：HANDOFF §1 的两个缺陷（max_outer 静默丢弃、压力有效性字面量）
  **均已在上游修复**（`8ea7ce5` + 2026-07-11 波），且 `test_validate_pipeline_runner_wiring.py`
  四断言已锁死——连"读 CAP 冒充实际迭代数"的细节（07-12 发现）都有断言
- 本轮证据：实跑 19 个锁定测试（wiring + truth-table）全绿 6.13s；无码可写，收案
- 勘误：审计报告 §0/§6 曾转述 HANDOFF §1 为"仍在"——已改；P4.4 列明 HANDOFF 三处确认过时
- **协议进化**：§1 新增"开工先现场核实条目前提"步骤（本轮的教训制度化）
- 下一步：P1.3 评估器 envelope 权威统一（真·未修的缺口，审计 §2 已核实）

## iter 6 · 2026-07-19 · P1.1 架构审计 ✅（`2426861` 工具, `0aa775e` 报告）—— **Phase 1 开篇**

- 三路取证：AST import 图（新工具入库，34 核心边、3 违规 + main↔ui 环）+ 双 evaluator 逐能力
  diff + run_stack_3d 解剖/可变态清单（两个只读侦察兵，file:line 全核对到当前代码）
- **修正性发现**：双 evaluator 是 2D/3D 两个 BO 评估器（不是同物两版）；HANDOFF §2a 预解、
  §3a 热重播种两行已过时（aa3f477 修过）；真缺口是 post-solve gate 双缺 + 3D 手抄 envelope
  代数 + rho_inlet_ref 双缺；run_stack_3d 无重复但单函数 1955 行（五缝已标）；
  两个 W7b 同族潜伏缓存隐患（compute_geometry 共享 dict、_phi_grid 未冻结）
- 产出 `docs/ARCHITECTURE-AUDIT-2026-07.md`（后续 P1 的工作底稿，与 HANDOFF 冲突以它为准）；
  **P1.3-P1.9 已按审计重写回填**
- 另：Alex 调频定时器 25→15 分钟档（job d7888157，7/22/37/52）
- 下一步：P1.2 正确性债（HANDOFF §1，唯一没被审计推翻的原条目）

## iter 5 · 2026-07-19 · P0.5 文档纠偏 + D1 执行 ✅（`c4cccb7`, `059d306`）—— **Phase 0 收官**

- **D1（Alex 拍板：a）**：golden_3d.json（2 KB）入库，meta 侧车同步，重基准规矩定为
  "json+meta 同 commit 带 `!`"
- /check：死路径 D:\Postgraduate → 中性仓库根表述；runner 入库注记；§2 按 D1 改写
  （3D 直接 --check 入库基线；2D 仍本地捕获）
- pytest.ini 头注：128 核 -n auto 警告 + CI=true 精确门语义（HANDOFF §9d 收编进配置现场）
- 验证：strict-markers 收集 + 定点 1 passed；meta json 解析过
- **Phase 0 安全网 5/5 完成**（基线快照、依赖锁、响亮回退、测试基建、文档纠偏）；
  下一步 P1.1 架构审计（Phase 1 开篇）

## iter 4 · 2026-07-19 · P0.4 测试基建入库 ✅（`6521ba7`）

- `scripts/run_tests_server.ps1` 入库——官方跑法结束"untracked by choice"状态
- `golden_3d.meta.json` 侧车入库：sha256 4ae326dc… + 认证 commit 4b32da4 + 三次位同记录 +
  环境指纹（HANDOFF §9"golden 零版本记录"缺口关闭；重基准须同 commit 更新侧车）
- **DECISIONS D1 待 Alex**：golden json 本体（2 KB 文本）入库与否，循环建议入库
- 验证：json.tool 解析过、sha256 与在盘一致；无运行时路径变化（免套件，PROTOCOL §4 资产级）
- 下一步：P0.5 文档纠偏（/check 死路径 + pytest.ini CI 语义头注）——P0 收官项

## iter 3 · 2026-07-19 · P0.3 回退改响亮 ✅（`cdbe14e`）

- prebuilt-CSV 标定回退：info → **WARNING + ASCII 横幅**（W6 的 ASCII-only 约束遵守；
  info 在默认 logging 配置下不可见正是陷阱静默的机理）
- `data-repo.pin` 入库（仓库根）：SJTU-TPMSHX-data @ 823847e；原定 data/ 内路径不可版本化，已偏离记档
- 新测试锁定 WARNING 级（tpmshx logger propagate=False，测试里显式挂 caplog.handler）
- 门禁：suite **1236+10 绿 / 4 skip / 0 败**（+1 新测试）、golden **位同**；xlsx 在位行为不变
- 下一步：P0.4 测试基建入库（golden meta 侧车 + runner 入库；golden json 入库与否 → DECISIONS）

## iter 2 · 2026-07-19 · P0.2 依赖锁定 ✅（`abaa348`）

- `requirements-lock-server.txt` 入库：80 包完整闭包（含 BO 栈），--extra-index-url 内置可一条直装，
  指纹与基线同源（76b60e32…）
- `requirements.txt` 三档头注：裸下界 / devbox constraints / server lock 各自用途；
  纠正 torch "Optional/GPU" 过时注释、写明 BO 栈缺席事实（HANDOFF §9e）
- 验证：pip --dry-run 双文件 exit 0（PROTOCOL §4 新增"依赖元数据"行，免套件有据）
- 下一步：P0.3 raw_data 静默回退改响亮（首个碰运行时代码的条目，全门禁伺候）

## iter 1 · 2026-07-19 · P0.1 基线快照 ✅（`2c51eca`）

- 四门证据链（suite → golden → 3D real → lumped）串行跑完全绿，日志落盘 upgrade/logs/p01-*
- 基线数字：套件 1245 绿 / 4 skip / 0 败（10:41 + 9.3s）；golden 位同；3D gate PASS
  （RMSRE_dP 4.88%、RMSRE_Q 2.12%，16/16 valid）；lumped cross-flow vs Q_air 1.73%（与 07-13 口径一致）
- 插曲：validate 运行会改写 tracked 的 shanghai_3d_baseline.csv——本轮 diff 为 ULP 尾噪（1e-13），
  已回退；该"自改写 tracked 产物"设计味道移交 P1.2。skip 3→4 的差异待顺手查明
- 下一步：P0.2 依赖锁定

## iter 0 · 2026-07-19 · 循环启动（人工，Alex 在场）

- 主检出的 sCO2 光滑壁闭合 WIP 先过全套 suite（双 pass exit 0，lastfailed 空）后提交为
  master `4b32da4`（37 文件 +4471），未 push
- worktree 建立：`E:\LWH\SJTU-TPMSHX-upgrade`，分支 `upgrade/loop`，基点 `4b32da4`
- 非跟踪资产复制：`data\`（17 MB，含 raw_data 与 sCO2-CFD）、`golden_3d.json`、
  `scripts\run_tests_server.ps1`
- 环境复刻：venv（C:\Python312 底座）+ 80 包精确冻结（torch==2.11.0+cpu 走 pytorch cpu 索引，
  其余走 PyPI，--no-deps 装完整闭包）
- 就绪门（全部通过，2026-07-19）：`pip check` 无破损依赖；worktree 内全套 suite 双 pass
  exit 0 且 `.pytest_cache` 无 lastfailed（零失败）；`_golden_3d.py --check golden_3d.json`
  位同（链条对 golden 失败有独立 exit 2 出口，走到底即位同）。精确计数因后台输出截断未留存，
  P0.1 重跑时落盘补记
- 决策记录（Alex，2026-07-19）：架构优先；**允许有据重基准**（PROTOCOL §5 的流程约束）；
  全天候 ~25 分钟一轮，撞 5h 限额自动等窗口重置续跑
- 决策补充（Alex，2026-07-19）：P0/P1 用 Fable 5 max 直做；P2 起循环自评——机械项派
  Sonnet 5/Opus 子代理执行、Fable 5 复核+验证+提交，判断项 Fable 5 直做（PROTOCOL §10）
