# Design: cleanup-ci

## Context

无 CI；测试套件本地 14:31（含 slow）。gitignored 资产：`models/*.joblib`（RBF 备用后端）、`data/`（实验 xlsx）。默认 surrogate 路径 gamma_df 只读 `_prebuilt/` CSV（tracked）。PySide6/CoolProp/预建 CSV 缺失时相关测试已有 skipif/importorskip 门（死代码扫描已清点）。

## Goals / Non-Goals

**Goals:** master 每次 push/PR 有自动 pytest 门；清理不可运行的死引用脚本；openspec 归档卫生。
**Non-Goals:** golden bit-identity 上 CI（跨机 FMA/线程差异 + 基线 gitignored，本地门足够）；Windows CI（开发机即 Windows，CI 补 Linux 视角反而多一层保障）；覆盖 slow 测试。

## Decisions

- **D1**：`git mv benchmarks/benchmark_a.py benchmarks/archive/` + 头注一行（task 3 目标已删，frozen record）。不修路径——它就是历史快照，修了也没有 batch_runner。
- **F1 workflow**：单 job，ubuntu-latest，py3.12，pip cache；安装 requirements.txt 里除 PySide6/pyvista/pyvistaqt/CoolProp 外的包（用独立安装列表而非改 requirements.txt——桌面依赖对本地仍必需）；`pytest sjtu_tpmshx/tests/ -q -m "not slow" --timeout=1200`（pytest-timeout 防挂）。`PYTHONHASHSEED=0` 固定（3D stack 已知 hash-seed 敏感）。
- **F2 首跑迭代**：push 后 `gh run watch`；失败逐个分类——环境缺件 → workflow 补装或测试补 skipif（不改被测逻辑）；真 bug → 单独处理并上报。
- **F3 归档**：restructure-1/2/3 任务补勾 + `openspec/changes/` → `archive/`（带原完成日期不可考，用今天日期归档并在 tasks 顶注明）。`df-coeffs-cfd-refit` 仍活跃（cF 阶段未做）——不动。

## Risks / Trade-offs

- [CI 首跑红] → 预期内，迭代到绿是任务的一部分（3.2）。
- [numba 在 CI 冷编译拖时长] → 无 cache=True 跨机缓存可用；接受（预估 15-25 min），必要时 job 级 `NUMBA_DISABLE_JIT` 不可取（会改数值路径），不做。
- [ubuntu 上路径/编码差异] → 测试若有硬编码 Windows 路径 → 补 skipif（属环境门，不改逻辑）。

## Migration Plan

纯增量。回滚 = 删 workflow 文件 + git mv 还原。
