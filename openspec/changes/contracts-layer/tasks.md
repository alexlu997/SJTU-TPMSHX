## 1. 勘察与基线

- [ ] 1.1 逐函数标注 `controllers/compute_config.py`：纯契约 vs 窗口采集（判据：签名含 window/widget 或 body 摸 Qt）；grep 所有 `from_window`/采集函数调用点确认全在 UI 层
- [ ] 1.2 golden 2D/3D 基线捕获（PYTHONHASHSEED=0）

## 2. 拆分与搬移（单 commit 原子）

- [ ] 2.1 纯契约 → `domain/compute_config.py`；`ComputeResult` → `domain/compute_result.py`；controllers 侧瘦身保留采集函数并从 domain import 类型
- [ ] 2.2 zone 采集的 `ui.zone_table` 依赖改注入（callable 参数，UI 调用方显式传入）；`theme_manager` → `ui/theme_manager.py`（改 2 测试 + controllers/__init__ 清理）
- [ ] 2.3 全仓 import 更新（sjtu_tpmshx + projects + benchmarks + examples + poc，~41+ 处），无 shim
- [ ] 2.4 deferred import 清理：stages_2d/stages_3d/compute_pipeline 破环项提升顶层，懒加载项注明理由（compute_pipeline→stages 视 import 耗时实测定夺，design Open Question）

## 3. 验证门

- [ ] 3.1 `pytest --collect-only` 零错误 + `import pipelines.stages_2d/3d` 不带入 controllers（spec 场景）
- [ ] 3.2 离屏 UI 冒烟（runs/smokes/smoke_ui_offscreen.py）通过
- [ ] 3.3 golden 2D/3D `--check` bit-identical
- [ ] 3.4 全量 pytest 0 failed；commit + push；CI 绿
