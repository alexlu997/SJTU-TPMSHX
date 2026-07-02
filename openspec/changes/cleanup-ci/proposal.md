# Proposal: cleanup-ci

## Why

架构扫描（2026-07-02，三路 agent：结构度量/依赖/死代码）后的第一批低风险高回报项（选项 D+F）：仓库有少量死引用与错位脚本；master 无任何 CI 护栏（无 .github），最近三次大 push 全裸落地。用户决策：polygon 功能链（polygon_fvm/unstructured_mesh/polygon_calc，~2.3k LOC）**保留**（后续方向）。

## What Changes

- **D（清理，缩小版）**：
  - `benchmarks/benchmark_a.py` → `benchmarks/archive/`（自述 frozen snapshot；其 task 3 目标 `validation/legacy/validate_shanghai.py` 已删，脚本已不可运行，纯历史记录）。
  - PROJECT_MANUAL 记录两条状态：polygon 链有意保留（后续方向）；`sigmoid_field_3d` 仅 demo/test 使用。
  - 不动：runs/ 根生产入口（restructure-2 约定）、sigmoid_field_3d 本体、polygon 链。
- **F（CI）**：
  - 新增 `.github/workflows/ci.yml`：ubuntu + Python 3.12，headless 依赖子集（无 PySide6/pyvista/CoolProp——对应测试有既有 skip 门），`pytest -m "not slow"`。
  - 依赖可行性已验证：默认 gamma_df 后端只需 `df_surrogate/_prebuilt/*.csv`（全部在 git）；gitignored 资产（joblib 模型、data/ xlsx）对应测试均有 skipif/env 门。
  - push 后用 gh 观察首跑，修到绿。
  - openspec 卫生：restructure-3 遗留任务勾完（工作已在 2161dfe 提交），三个 restructure change 归档。

## Capabilities

### New Capabilities
- `repo-ci`: 仓库持续集成门（headless pytest 子集）及其排除约定。

### Modified Capabilities

（无）

## Impact

- 代码零行为变化（纯移动 + 新增 workflow + 文档）。golden 不涉及。
- 风险：CI 首跑可能暴露 Linux/缺资产路径问题 → 迭代修 workflow 或补 skipif（不改被测逻辑）。
