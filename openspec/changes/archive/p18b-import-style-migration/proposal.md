# p18b-import-style-migration

## Why

P1.8（`827bee9`）立了打包地基（pyproject + `tpmshx-run`），但留下"诚实注记"欠账
（pyproject.toml:3-6）：库内约 165 个模块统一用顶层导入风格（`from solvers import ...`），
靠 **135 个文件**里的 sys.path 引导块撑着（实测 2026-07-21：tests 73 / runs 35 /
validation 17 / df_surrogate 7 / ui 1；核心库目录自身干净——裸导入，依赖调用方引导）。

核心隐患是**双风格混用陷阱**：`solvers.X` 与 `sjtu_tpmshx.solvers.X` 在 CPython 里是
**两个不同的模块对象**（sys.modules 两个键），模块级状态各存一份——warn-once 注册表
（`nu_correlations._EXTRAP_WARNED`、`predict._CHOKE_WARNED`）、logutil 的 logger 配置、
`_FIELD_CACHE` 等全部翻倍，出的 bug 静默且难排查。P1.7 当年裁定"零星清理回归面大收益负"，
专等本波次结构性根治。

## What Changes

- **W0（本变更首个提交）：过渡期身份垫片 + editable 地基**
  - 新建 `sjtu_tpmshx/__init__.py`（此前为 namespace package，无 init）：
    ① 自举——把包目录插入 sys.path（迁移期**唯一钦定**引导块，代替全库 135 处）；
    ② **身份 meta-path finder**——把任意 `sjtu_tpmshx.X[.Y...]` 导入重定向为顶层
    `X[.Y...]` 的**同一模块对象**（sys.modules 双键同对象）。父包 init 必先于任何
    子模块导入执行 ⇒ 垫片对所有包风格导入全覆盖 ⇒ **双风格从此无法产生双对象**，
    后续波次任意顺序、任意粒度迁移都安全；
  - 身份测试 `tests/test_import_identity_shim.py`（双风格同对象、深层同对象、
    注册表共享、finder 幂等）；
  - 工作 venv `pip install -e . --no-deps` + `pip check`（P1.8 当时刻意"venv 未动"，
    W0 起用）；
  - pyproject 头注从"迁移前请勿混用"改写为"垫片已使混用安全，迁移进行中"。
- **W1..Wn（后续迭代，§10 委托候选）：调用方机械迁移波次**
  按目录分波：tests（73 文件）→ validation（17）→ runs（35）→ df_surrogate（7）→
  ui（1）。每文件：删 sys.path 引导块，顶层导入改 `sjtu_tpmshx.*`。每波全门。
- **W_final（收尾）：库内改写 + 撤垫片**
  库内 165 模块顶层风格 → `sjtu_tpmshx.*` 原子改写；撤 finder 与自举（`__init__.py`
  瘦身为普通包 init）；pyproject 注记收尾；顺带并入 P1.5 尾巴（run_stack_3d 五阶段
  函数文件级迁移 → `run_stack_3d_stages.py`）。

## Non-goals

- 不改任何数值路径、不动求解器语义——golden 位同是每波硬门；
- 不做 ruff format / 行号重排（P2.1c 裁决维持：atlas file:line 引用与 wiring 断言优先）；
- `archive/` 冻结区、`docs/` 内嵌片段不迁移（只注记）。

## Capabilities

### Modified Capabilities

- **packaging**：`sjtu_tpmshx` 从 namespace package 变为 regular package（新增
  `__init__.py`）；`pip install -e .` 成为工作 venv 的标准形态；迁移完成后包外
  调用方可直接 `from sjtu_tpmshx.solvers import ...` 无需任何路径黑客。

### Migration Invariants（每波必须保持）

1. golden_3d `--check` 位同；全套 suite 双 pass 绿；
2. 身份测试常绿（垫片在位期间双风格必同对象）；
3. `tpmshx-run` console script 可启动（`--help` exit 0）；
4. 迁移过的文件不得再含 sys.path 操作（波次收尾 grep 断言）。
