## 1. D — 清理

- [x] 1.1 `git mv benchmarks/benchmark_a.py benchmarks/archive/` + 头注补"task 3 目标已删，纯冻结记录"
- [x] 1.2 PROJECT_MANUAL：polygon 链有意保留（后续方向）、sigmoid_field_3d 仅 demo/test 两条状态注记

## 2. F — CI

- [x] 2.1 `.github/workflows/ci.yml`：ubuntu + py3.12 + pip cache，`PYTHONHASHSEED=0`，`pytest -m "not slow"` + pytest-timeout
- [x] 2.2 本地 `--collect-only` 1032 collected 无收集错误
- [x] 2.3 openspec 卫生：restructure-1/2/3 补勾（工作已在 5fa5b0f/4422d3d/2161dfe 提交）并归档
- [x] 2.4 三轮迭代至绿：①缺 PySide6（控制器测试无 skip 门）→ 装 PySide6+offscreen+Qt 系统库；②CoolProp 运行时 ImportError（32 个）+ skimage 缺（requirements.txt 本来就漏）→ 都装上；ULP 精确断言（df backend/projection 同机 bit-repro 门）加 `CI=true` skip；data/ xlsx 测试加存在性门 → **run 28597107501 success**

## 3. 收尾

- [x] 3.1 本地全量 pytest 复跑绿（1056+4 passed / 0 failed，与 contracts-layer 合并验证），归档本 change
