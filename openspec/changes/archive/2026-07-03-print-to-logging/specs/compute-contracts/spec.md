# compute-contracts Delta — print-to-logging

## ADDED Requirements

### Requirement: Central logging with GUI-capture-safe stdout handler
生产包（solvers/pipelines/controllers/df_surrogate/optimization/core/ui 库路径）的运行时输出 SHALL 走 `logutil.get_logger`（`tpmshx` 根 logger）。Handler SHALL 逐条解析当前 `sys.stdout`（非创建时绑定）——保证 `compute_orchestrator` 的 `redirect_stdout` 求解日志捕获不丢日志。默认渲染 SHALL 为裸消息（与旧 print 字节兼容）；`TPMSHX_LOG_TS=1` SHALL 加时间戳前缀；`TPMSHX_LOG_LEVEL` SHALL 控制级别（默认 INFO）。@njit 内与 CLI/`__main__` 路径的 print SHALL 保留。既有 `verbose` 门语义 SHALL 不变（logging 级别在其上叠加过滤，不替代）。

#### Scenario: Solve-log viewer still captures solver output
- **WHEN** GUI 跑一次 compute（orchestrator redirect_stdout 捕获）
- **THEN** 日志缓冲含转换后的 logger 输出（如 "[3D grid]" 行）

#### Scenario: Default output unchanged
- **WHEN** 未设任何 TPMSHX_LOG_* 环境变量跑一次求解
- **THEN** stdout 逐行字符串与转换前 print 输出一致

#### Scenario: Level filter works
- **WHEN** `TPMSHX_LOG_LEVEL=ERROR` 下跑求解
- **THEN** info 级求解 chatter 不出现
