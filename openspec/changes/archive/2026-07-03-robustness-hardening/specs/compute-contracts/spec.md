# compute-contracts Delta — robustness-hardening

## ADDED Requirements

### Requirement: Finite-positive input gates at every boundary
非有限（NaN/inf）或非正的物理标量 SHALL 在三个咽喉被拒：窗口 strict 校验（`_validate_required_widgets`，temp 类字段原文可为负 °C、只查有限性）、字段 blur 校验（"Must be finite"）、`ComputeConfig.validate()`（`from_dict`/`from_json` 必经；直接构造保持宽松供测试用）。`validate_geometry` SHALL 接入 `_preflight_grid` 运行路径（硬错弹窗阻断、软警合并进预检报告）。

#### Scenario: NaN rejected at the script boundary
- **WHEN** `ComputeConfig.from_json` 读入含 `NaN` 的 JSON
- **THEN** 抛 ValueError（不再静默进入求解器）

#### Scenario: Negative Celsius still accepted
- **WHEN** °C 模式下 T_in 原文为 "-10"
- **THEN** 窗口 strict 校验通过（开尔文正性由 validate() 把关）

### Requirement: First-class convergence verdict
`ComputeResult` SHALL 携带 `converged: bool`：2D = 外耦合收敛且无 SIMPLE 停滞；3D = 无 SIMPLE 停滞且最后一轮 LTNE 达标（早期外迭代打满帽不算失败）。False 时 UI SHALL 前置用户警告并在诊断摘要标注"否（结果仅供参考）"。

#### Scenario: Diverged solve is visibly flagged
- **WHEN** raw['solver_converged']=False 的结果进入 write_result
- **THEN** result.warnings 首条为未收敛提示，诊断摘要含"收敛: 否"

### Requirement: 3D cell cap on every path
`_run_3d_stack` SHALL 在网格单元数超过上限（默认 2,000,000；`TPMSHX_MAX_CELLS_3D` 或 `cfg['max_cells_3d']` 显式放宽）时抛 ValueError（含 RAM 估算），使脚本/优化器路径与 UI 同受保护；UI 大网格对话框 SHALL 显示工作内存估算。

#### Scenario: Script path blocked before allocation
- **WHEN** cap=1000 下以 2000 单元 cfg 调 `_run_3d_stack`
- **THEN** 求解前抛 ValueError（消息含 "cell cap"）

### Requirement: Corrupt persistence quarantined
损坏的会话/预设 JSON SHALL 被重命名为 `<name>.corrupt-<ts>`（best-effort）而非静默回退默认并被下次保存覆盖。

#### Scenario: Corrupt session recoverable
- **WHEN** `.last_session.json` 内容非法 JSON 且调用 load_session
- **THEN** 返回 None 且目录中出现 `.corrupt-*` 隔离文件
