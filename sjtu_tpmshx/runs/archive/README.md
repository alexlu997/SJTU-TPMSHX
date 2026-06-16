# runs/archive — 历史诊断快照

2026-05-14 前后的一次性诊断脚本, 所验证的 bug (ε 双减半 / partial-B ghost 污染)
已在 master 修复并由测试守护。仅作历史记录保留, 不维护、不保证可运行。

## 2026-06-16 归档批次

死代码审计后从 `runs/` 与 `validation/` 移入的一次性诊断 / 已定稿验证脚本
(0 处 import、0 处 doc/CI 引用)。结论已进 memory/vault, 脚本仅留史。
注: 原 `sys.path` 引导按移动前目录深度计算, 移入本目录后会指偏, **不保证可直接运行**。

- `diag_ab_imbal.py` — A/B 能量不平衡诊断
- `diag_df_model_zoo.py` — D-F 代理 17 变体模型动物园
- `diag_rbf_feature_ablation.py` — RBF 特征消融
- `diag_shanghai_flow_topology.py` — 上海工况流动拓扑诊断
- `nu_eps_vs_dhl_diag.py` — Nu(ε) vs Nu(D_h/L) 对比
- `phase_b_postprocess.py` — V&V Phase B gate 修正后一次性 re-classification
- `validate_d76_3d.py` — d76 baseline 快照 (基线已重定, 见 memory)
- `cross_check_water_nu.py` — 水侧 Yan[6] Nu 交叉核 (已定稿)
