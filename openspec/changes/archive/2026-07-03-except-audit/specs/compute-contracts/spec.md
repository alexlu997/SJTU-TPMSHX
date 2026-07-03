# compute-contracts Delta — except-audit

## ADDED Requirements

### Requirement: No silent degradation in solver-side exception fallbacks
求解侧（solvers/pipelines/controllers/optimization 生产路径）的异常兜底 SHALL NOT 静默：物理量降级兜底（质量加权 → 朴素均值、ṁ→0、GP 未拟合继续）SHALL 发 warning；仅预期异常 SHALL 用窄类型捕获（如属性缺失 → AttributeError）；确属设计的 broad except（stdout tee、JIT warmup、LUT 缓存回退、UI 进度回调守卫）SHALL 带注释说明理由。UI 层 best-effort（会话恢复等）不在此约束内。

#### Scenario: Flux-weighting failure is loud
- **WHEN** `_face_flux_weights` 在 `_mass_weighted_T_out` 内抛异常
- **THEN** 返回朴素均值兜底且发 UserWarning（含失败原因与"T_out/Q degraded"）

#### Scenario: Production GP fit failure warns
- **WHEN** `fit_gpytorch_mll` 抛异常且 verbose=False
- **THEN** 发 warning（不再静默继续未拟合 GP）

#### Scenario: Golden unchanged
- **WHEN** 金档 2D/3D --check 在本变更后运行
- **THEN** PASS (bit-identical)
