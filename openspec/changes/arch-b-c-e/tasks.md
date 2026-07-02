## 1. B — kernel DAG

- [ ] 1.1 建 `solvers/tpms_props.py`（常数/警告助手/air_*/water_*/CHI_S/geometry 移入），`tpms_calc` 显式 re-export；AST 校验 + golden 双 `--check`
- [ ] 1.2 df_surrogate 全部改 import 叶子（5 顶层文件 + predict/surrogate_domain deferred 提升；sCO2 fluid_props deferral 保留注明）
- [ ] 1.3 solvers 侧 deferred df import 提升顶层（tpms_calc/df_projection/simple_solver/polygon_fvm）
- [ ] 1.4 新增 import-DAG 测试（df_surrogate.predict 不拉 tpms_calc/simple_solver）；B commit

## 2. C — solve 骨架单源

- [ ] 2.1 `solvers/_solve_common.py`：LowReExit（参数读取 + 判据 + prev 更新），浮点次序与两份现行逐运算一致
- [ ] 2.2 2D/3D solve() 换用共享实现（收尾各自保留）；golden 2D/3D bit-identical 硬门（不平不合，禁止重基线）
- [ ] 2.3 R1 早退测试复跑 + 全量 pytest；C commit

## 3. E — UI 减肥

- [ ] 3.1 扫 main.py 方法分组，选 1-2 个内聚块（优先：结果写回/绘图胶水、菜单构建）
- [ ] 3.2 抽入 mixins（既有或新建），main.py ≤ ~2000 行；离屏 UI pytest 子集过
- [ ] 3.3 panel_vis_3d：有无 Qt 辅助函数群则抽 helpers，否则记录放弃理由
- [ ] 3.4 全量 pytest + golden 双检；E commit

## 4. 收尾

- [ ] 4.1 push 全部，CI 绿；PROJECT_MANUAL 更新（tpms_props/_solve_common/新 mixin 条目）；归档本 change
