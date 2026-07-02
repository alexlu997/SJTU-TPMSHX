## 1. 勘察与基线

- [x] 1.1 逐函数标注完成：契约（dataclasses/bc_to_dict/from_json 族）vs 采集（_qt_*/_read_*/from_qt_window，全鸭子类型无 Qt import）；`from_qt_window` 生产调用点仅 run_controller 2 处 + 2 测试文件 → design D1 修订为"采集移 ui/window_config.py"，注入方案弃用
- [x] 1.2 golden 2D/3D 基线验证有效（--check 双 PASS，PYTHONHASHSEED=0）

## 2. 拆分与搬移（单 commit 原子）

- [x] 2.1 纯契约 → `domain/compute_config.py`；`ComputeResult` → `domain/compute_result.py`；采集 → `ui/window_config.py`（`config_from_window` 自由函数，行区间抽取脚本 + AST 校验）；`controllers/compute_config.py` 删除
- [x] 2.2 `theme_manager` → `ui/theme_manager.py`（field_factory/2 测试/controllers/__init__ 更新）
- [x] 2.3 全仓 import 更新（30 文件机械重写 + run_controller/2 契约测试文件手工拆分），无 shim
- [x] 2.4 deferred import 清理：stages_2d/3d 的 ComputeResult 提升顶层 + stale 环注释更新；compute_pipeline→stages 保持懒加载（numba 链 GUI 冷启动开销）并注明

## 3. 验证门

- [x] 3.1 `--collect-only` 1032 collected 零错误；`import pipelines.stages_2d/3d` 后 sys.modules 无 controllers（DAG 成立）；`config_from_window` 裸 stub 冒烟通过
- [x] 3.2 离屏 UI 冒烟 — **预存环境失败**（HEAD 上同样 exit 1：本机 PySide6 缺 Qt 字体目录，与本 change 无关；stash 判别验证）。UI 构造覆盖由全量 pytest 的 test_main_smoke 等承担
- [x] 3.3 golden 2D/3D `--check` 双 PASS (bit-identical)
- [x] 3.4 全量 pytest 1056+4 passed / 0 failed（main.py 多名 import 漏改致 3 个 UI smoke 失败，修复后复跑绿）；commit `48b97c6` + push；CI run 28597107501 **success**
