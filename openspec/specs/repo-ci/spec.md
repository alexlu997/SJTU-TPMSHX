# repo-ci Specification

## Purpose
仓库 CI 门（GitHub Actions，headless pytest 子集）及其安装/排除约定。来自 openspec archive `2026-07-02-cleanup-ci`（架构扫描批次 D+F）。

## Requirements

### Requirement: Headless CI gate on push/PR
仓库 SHALL 提供 GitHub Actions workflow（`.github/workflows/ci.yml`），在 push 到 master 与 PR 时运行 `pytest sjtu_tpmshx/tests/ -m "not slow"`（ubuntu，Python 3.12，`PYTHONHASHSEED=0`）。桌面/可选依赖（PySide6、pyvista、CoolProp）SHALL NOT 安装——对应测试依既有 skip 门自动跳过。CI SHALL NOT 依赖任何 gitignored 资产（joblib 模型、data/ 原始 xlsx）。

#### Scenario: CI green on a clean master
- **WHEN** workflow 在当前 master 运行
- **THEN** pytest 子集 0 failed（skipped 允许），职位状态绿

#### Scenario: Environment-gated tests skip, not fail
- **WHEN** CI 环境缺 PySide6/CoolProp/本地资产
- **THEN** 相关测试被 skip 而非 fail

### Requirement: Dead-reference cleanup with history preserved
不可运行的历史基准脚本 `benchmarks/benchmark_a.py`（目标脚本已删除）SHALL 移入 `benchmarks/archive/` 并在头注标明冻结原因；polygon 功能链与 `sigmoid_field_3d` 的保留状态 SHALL 记入 PROJECT_MANUAL（有意保留，非遗漏）。

#### Scenario: No dangling runnable references
- **WHEN** 搜索仓库内对 `validation/legacy/validate_shanghai.py` 的非注释引用
- **THEN** 仅存在于 archive 与文档中，无声称可运行的脚本引用它

### Requirement: openspec archive hygiene
已完成的 restructure-1/2/3 changes SHALL 补勾遗留任务（对应工作已提交，注明 commit）并归档至 `openspec/changes/archive/`；活跃 change（df-coeffs-cfd-refit）SHALL NOT 被动。

#### Scenario: Active list reflects reality
- **WHEN** 运行 `openspec list`
- **THEN** 仅剩真实活跃的 change
