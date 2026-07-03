# compute-contracts Delta — pipeline-stage-dedup

## ADDED Requirements

### Requirement: Shared stage scaffolding single source
2D/3D 管线的非内核胶水 SHALL 单一来源于 `pipelines/_stage_common.py`：域尺寸单位滑移防火墙（`validate_domain_dims`，>10 m 抛 ValueError）、双侧代理训练域守卫（`surrogate_extrap_reasons`：ImportError → 跳过返回 []，ValueError 上抛）、headline 标量守卫（`safe_float`：None/非数 → nan）、props 槽几何三元组（`geometry_props`）。stages_2d 与 stages_3d SHALL NOT 各自持有这些逻辑的副本。数值内核 SHALL 保持每维独立（统一已被否决）。

#### Scenario: Unit-slip rejected identically in 2D and 3D
- **WHEN** L_dom_m=182.0（把 mm 值误填进米字段）进入任一维度的 parse
- **THEN** 抛 ValueError，消息含 "exceeds" 与 "unit slip"

#### Scenario: Broken extrap guard fails loudly (2D hush removed)
- **WHEN** 代理域检查内部抛 AttributeError
- **THEN** 异常向上传播（不再被 2D 静默吞掉禁用外推警告）

#### Scenario: None headline does not crash 2D finalize
- **WHEN** raw['Q_total'] 为显式 None
- **THEN** ComputeResult.Q_W == nan（而非 TypeError）

#### Scenario: Golden gates bit-identical
- **WHEN** `_golden_2d.py --check` / `_golden_3d.py --check`（PYTHONHASHSEED=0）在本变更前后各跑一次
- **THEN** 四次全部 PASS (bit-identical)
