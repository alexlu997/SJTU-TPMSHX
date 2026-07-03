# compute-contracts Delta — perf-wave1

## ADDED Requirements

### Requirement: First-wave performance levers stay bit-identical
以下性能改动 SHALL 保持金档 2D/3D 位相同：几何缓存扩容（`_compute_raw` lru ≥2048、`compute_geometry` lru ≥4096——纯缓存容量，命中值不变）；`_build_hv_local_2d` 均匀路径向量化（逐元素镜像 3D perf-B1 变换：Re 预下限 1.0、Nu 后下限、ε_f=ε/2）；2D A/B 两股 SIMPLE 求解并行（独立求解器、无共享写状态，仅墙钟变化）；BO loky worker 线程数 = cores//n_jobs（默认路径 n_jobs=1 不受影响）。会改变迭代轨迹或浮点次序的深层优化（2D 温启动、PP-AMG、并行门默认值、3D 外迭代重解并行、RB 2D 能量）SHALL 记录为显式的重基线决策，不混入本批。

#### Scenario: Golden bit-identical after wave 1
- **WHEN** 金档 2D/3D --check 在本变更后运行（PYTHONHASHSEED=0）
- **THEN** PASS (bit-identical)

#### Scenario: Threaded 2D A/B produces the sequential result
- **WHEN** 同一 cfg 在并行 A/B 下求解
- **THEN** 全部输出场与串行版本位相同（金档即证）

#### Scenario: Cache growth changes no values
- **WHEN** 相同 (tpms, L, t) 查询命中扩容后的缓存
- **THEN** 返回值与未缓存计算一致（lru 语义）
