## 1. D — 清理

- [ ] 1.1 `git mv benchmarks/benchmark_a.py benchmarks/archive/` + 头注补"task 3 目标已删，纯冻结记录"
- [ ] 1.2 PROJECT_MANUAL：polygon 链有意保留（后续方向）、sigmoid_field_3d 仅 demo/test 两条状态注记

## 2. F — CI

- [ ] 2.1 `.github/workflows/ci.yml`：ubuntu + py3.12 + pip cache，headless 依赖列表，`PYTHONHASHSEED=0`，`pytest -m "not slow"` + pytest-timeout
- [ ] 2.2 本地快速自查：`pytest -m "not slow" --collect-only` 无收集错误
- [ ] 2.3 openspec 卫生：restructure-1/2/3 补勾（注明 commit 5fa5b0f/4422d3d/2161dfe）并归档
- [ ] 2.4 commit + push，`gh run watch` 首跑；红则迭代（补装依赖/补 skipif，不改被测逻辑）至绿

## 3. 收尾

- [ ] 3.1 本地全量 pytest 复跑确认无回归（清理是纯移动，预期绿），归档本 change
