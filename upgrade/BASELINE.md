# 基线快照（BASELINE）— 2026-07-19 · iter 1 · P0.1

代码态 = master `4b32da4`（分支 upgrade/loop）。此后所有"数字没变"的断言对照本文件。
环境：venv C:\Python312 底座；冻结指纹 sha256 `76b60e32…f555a6`（80 包，torch==2.11.0+cpu 装自 pytorch cpu 索引）；PYTHONHASHSEED=0、OMP/OPENBLAS/MKL/NUMEXPR/NUMBA 线程全钉 1、QT_QPA_PLATFORM=offscreen；AMD EPYC 7B13 ×2、高性能电源计划。
证据日志：`upgrade/logs/p01-*.log`（gitignored，本地留存）。

## 1. 测试套件（scripts/run_tests_server.ps1，双 pass）

- Pass 1（-n 64 worksteal，除顺序敏感模块）：**1235 passed, 4 skipped**，161 warnings，641.58s（10:41）
- Pass 2（test_df_projection_equivalence.py 串行原序）：**10 passed**，9.32s
- 合计 **1245 通过 / 4 skip / 0 失败**，runner 判 READY
- 注：2026-07-13 迁移基线为 1245 passed / **3** skipped——skip 多了 1 个，后续轮次顺手查明是哪个用例、何条件触发（不阻塞）
- slowest 15 概览（P3.1 fast-tier 的输入）：conservation_3d_energy[T4_partial_offset] 602s、[T3_partial_aligned] 513s、wall_refine_3d 459s、partial_bc_ghost_b 组 141–308s、asym_porosity_3d 组 168–303s、conservation[T2_full_cross] 116s；完整清单见 p01-suite.log

## 2. Golden 3D（_golden_3d.py --check golden_3d.json）

- **PASS（bit-identical）**
- 伴随良性 UserWarning（water Nu extrap，Re 低端越窗）——正常运行即有，非本轮新增

## 3. validate_shanghai_3d_real.py（bare 调用，Grid 20×10×3，Gyroid L=7.0 t=0.6）

- 16 工况全部 valid，0 个 pressure-INVALID（clip fired）
- **RMSRE_dP = 4.88%**（gate 限 12.0%；2D 基线 8.62%），max|err_dP| = 15.97%
- **RMSRE_Q = 2.12%**（gate 限 6.0%；2D 基线 2.49%），max|err_Q| = 7.16%
- **GATE PASS**
- 产物：`sjtu_tpmshx/validation/shanghai_3d_baseline.csv`——**被 git 跟踪**且脚本每次运行都改写；
  本轮复现到 ULP 级（第 13–16 位有效数字尾噪，1e-13 相对），已 `git checkout --` 回退工作树噪声。
  "tracked 产物被 bare 运行自改写"是个设计小味道，P1.2 动该脚本时一并处理（check 模式不落盘或写 _out/）
- ⚠ 口径注记：bare 调用走 production Pipeline3D dual-solve（脚本自述 "NOT the gate runner"）——
  正是 HANDOFF §1 的 max_outer 透传缺陷所在路径（本次外循环 max_outer=12 显示、各工况 outer=3 收敛）。
  P1.2 修复透传后本节数字可能移动，届时按 PROTOCOL §5 流程重记并说明

## 4. validate_shanghai_lumped_dual_nu.py（16 工况 ε-NTU 双 Nu）

- cross-flow（primary，Shanghai air⊥water）：**vs Q_air RMSRE 1.73%**（bias −1.29%，max 3.80%）；
  vs Q_water 17.00%（bias +15.72%，已知单侧口径差）；vs Q_avg 6.84%
- counter-flow（敏感性）：vs Q_air 1.51% / vs Q_water 17.30% / vs Q_avg 7.10%
- 与 2026-07-13 重基线口径一致（1.73%，f9a44a8 体素 N=128 后）✓
- 产物：data/shanghai_lumped_dual_nu.csv（脚本写入 data/，gitignored）

## 5. 观察（不阻塞，供后续条目引用）

- validate_3d_real 每工况打印大量 ConstDF-v1 / Nu 外推 UserWarning——P2.4 日志策略的现成素材
- 工具链教训：PowerShell 后台任务的控制台回显会丢 pytest 尾巴；Tee-Object 各阶段编码不一
  （suite 段 UTF-16LE、python 段 UTF-8）。规矩：证据一律读落盘日志文件，别信回显；
  必要时 iconv 探测两种编码

## 修订 2026-07-23 · iter 71 · R1 重基准（merge master 7ebdf6e 水/sCO2 关联式重拟）

根因 = WATER_NU_COEFFS 重拟（修正水 CFD 上传，Nu_dev 口径）+ SCO2_NU_COEFFS 重拟
（真 7/6 CFD）+ GAMMA_NU_SCO2 重冻（D 1.7558→1.8071、G 1.0744→1.1254）。
自本节起，"数字没变"的断言对照以下新值：

- 套件：**1306 passed / 3 skipped + 10 串行**（双 pass，4:49）
- Golden 3D：重采（`!` commit，json+meta 同轮）；破位只在 water_b 例
  （air_air 位同）：Q −0.45%、dP +0.09%；2D 同形态（基线在 job tmp，
  golden_2d_post_r1.json）
- validate_shanghai_3d_real：16/16 valid，**RMSRE_dP 4.88%（持平）/
  RMSRE_Q 2.11%（原 2.12%）**，GATE PASS——水 Nu 下修被空气侧限制吸收
- lumped dual-nu：cross vs Q_air **1.76%**（原 1.73%）/ Q_water 16.96%
  （原 17.00%）/ Q_avg 6.80%（原 6.84%）；counter 1.53%
- §1 的 skip 计数注：3 skipped 自 iter 64 Gate A 解锁后的新常态
