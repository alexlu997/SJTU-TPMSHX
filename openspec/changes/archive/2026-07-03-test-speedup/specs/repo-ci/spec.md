# repo-ci Delta — test-speedup

## MODIFIED Requirements

### Requirement: Headless CI gate on push/PR
仓库 SHALL 提供 GitHub Actions workflow（`.github/workflows/ci.yml`），在 push 到 master 与 PR 时运行 `pytest sjtu_tpmshx/tests/ -m "not slow"`（ubuntu，Python 3.12，`PYTHONHASHSEED=0`，`--timeout=600 --timeout-method=thread`）。PySide6（offscreen）与 CoolProp SHALL 安装（大量 controller/pipeline 测试在模块顶部无门 import Qt；一批 sCO2 测试运行时 raise 而非 import 门）；pyvista SHALL NOT 安装——对应测试依既有 skip 门自动跳过。CI SHALL NOT 依赖任何 gitignored 资产（joblib 模型、data/ 原始 xlsx）。CI SHALL 保持单进程（不并行）——thread-mode timeout 的挂起诊断与 xdist 交互未验证，属显式非目标。

#### Scenario: CI green on a clean master
- **WHEN** workflow 在当前 master 运行
- **THEN** pytest 子集 0 failed（skipped 允许），职位状态绿

#### Scenario: Environment-gated tests skip, not fail
- **WHEN** CI 环境缺 pyvista/本地资产
- **THEN** 相关测试被 skip 而非 fail

## ADDED Requirements

### Requirement: Pytest config single source
仓库根 SHALL 提供 `pytest.ini`：`testpaths = sjtu_tpmshx/tests`（裸 `pytest` 不得收集 `.claude/worktrees/` 内的仓库副本）、`--strict-markers`、注册 `slow` 与 `fast` 标记。未注册标记 SHALL 导致收集期报错而非静默通过。

#### Scenario: Bare pytest collects only the real suite
- **WHEN** 在仓库根运行 `pytest --collect-only -q`
- **THEN** 收集项全部位于 `sjtu_tpmshx/tests/`，无 worktree 副本

#### Scenario: Typo'd marker fails loudly
- **WHEN** 某测试使用未注册标记（如 `@pytest.mark.slwo`）
- **THEN** pytest 收集期报错

### Requirement: Parallel local gate
本地全量门 SHALL 支持 pytest-xdist 并行：`pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`，且 SHELL 层先设 `PYTHONHASHSEED=0`（3D 管线输出对 hash seed 敏感；env 无法从 pytest 配置内钉住）。`--dist loadscope` SHALL 为文档化默认（保持 module-scoped fixture 不跨 worker 重建）。pytest-xdist SHALL 列入 requirements.txt。

#### Scenario: Parallel full suite green
- **WHEN** `PYTHONHASHSEED=0` 下运行 `pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`
- **THEN** 结果与单进程一致（0 failed），墙钟时间显著低于单进程基线（~16 min）

### Requirement: Slow-marking policy — studies out, invariant gates in
`slow` 标记 SHALL 按角色而非单纯耗时：实测 > ~45 s 且属**研究型/冗余等价型**（网格收敛研究、优化器质量对比、并行==串行等价）且同路径有廉价覆盖存留的测试标 `slow`；**不变量门**（严格能量守恒 `test_conservation_3d_energy`、asym δ=0 位相同 `test_asym_porosity_3d`、sizing golden）无论耗时 SHALL NOT 标 `slow`（CI 必须保留）。标记 SHALL 逐测试而非整模块。全量本地门（无 `-m` 过滤）仍 SHALL 是 "done" 判据。

#### Scenario: Fast subset materially faster
- **WHEN** 运行 `pytest sjtu_tpmshx/tests/ -q -m "not slow" -n auto --dist loadscope`
- **THEN** 0 failed，且墙钟时间低于全量并行运行
