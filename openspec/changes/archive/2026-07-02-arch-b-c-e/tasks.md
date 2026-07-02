## 1. B — kernel DAG

- [x] 1.1 `solvers/tpms_props.py` 建成（geometry/air_*/water_*/CHI_S/警告助手 verbatim 移入），`tpms_calc` 显式 re-export（compute() 的 `_tpms_geom` 直接引用补回 import）；golden 双 PASS
- [x] 1.2 df_surrogate 6 文件改 import 叶子；surrogate_domain deferred 提升顶层，sCO2 fluid_props deferral 注明 runtime-only
- [x] 1.3 solvers 侧 7 处 deferred df import 提升顶层（tpms_calc/df_projection/simple_solver/polygon_fvm）
- [x] 1.4 `tests/test_import_dag.py`（3 探针：df 不拉 kernel、tpms_props 是叶子、pipelines 不拉 controllers）；gamma_df golden-point 精确值不变；commit `96a2840`

## 2. C — solve 骨架单源

- [x] 2.1 `solvers/_solve_common.py` LowReExit（max 归约次序与原两份逐运算一致；prev 更新语义保真：exit 路径不更新、min_iter 前更新）
- [x] 2.2 2D（min_iter=20 + `_enforce_mass_conservation` 收尾留 caller）/3D（min_iter=10）接入；golden 2D/3D **bit-identical PASS**（硬门过，无重基线）
- [x] 2.3 R1 早退测试 3/3 复跑绿；commit `e78fea6`

## 3. E — UI 减肥

- [x] 3.1 扫描定块：外观切换（accent/density/theme/immersive/left-panel，~230 行）+ 预设/工作区/会话持久化（~515 行）
- [x] 3.2 `ui/mixins/appearance.py` + `ui/mixins/session_presets.py`（verbatim 行区间抽取），main.py 2696 → **1954 行**；离屏 UI pytest 23/23 过
- [x] 3.3 panel_vis_3d **放弃拆分（有据）**：单个内聚 ThreeDVisPanel Qt 类 + 145 行 QSS 字符串构造器，无非 Qt 函数群切面；拆 Qt 方法跨文件反伤可读性
- [x] 3.4 golden 双 PASS + 全量 pytest；E commit

## 4. 收尾

- [x] 4.1 三 commit 推送（96a2840/e78fea6/3797648），CI run 28602198020 **success**；PROJECT_MANUAL 更新（tpms_props/_solve_common 条目）；备注时效性清理（用户加请求：14 处指向已迁移模块的过期注释修正——run_calculation→pipelines、validate_shanghai→aligned、from_qt_window→config_from_window 等；历史溯源注释保留）；归档本 change
