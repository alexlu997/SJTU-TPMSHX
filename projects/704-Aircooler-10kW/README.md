# 704 — 10kW 空冷器定尺

项目合作交付：10 kW 空冷器（air-cooler）定尺与热约束校核（组会交付）。驱动脚本调用主代码包 `sjtu_tpmshx/` 的 `design` 定尺工具与求解器。

## 脚本

| 脚本 | 用途 |
|---|---|
| `predict_aircooler_10kw.py`（756 行） | 一次性：10 kW 空冷器定尺，覆盖 3 个工况；提供 `build_cases()`。 |
| `aircooler_conservative_check.py` | 校核定尺结果是否满足热约束（保守 3D 复核）。`from predict_aircooler_10kw import build_cases`——与上一个脚本是同目录兄弟导入，二者必须放在一起。 |

## 运行（从仓库根目录）

```bash
python -u projects/704-Aircooler-10kW/predict_aircooler_10kw.py
python -u projects/704-Aircooler-10kW/aircooler_conservative_check.py
```

> 包挂载锚点为 `Path(__file__).resolve().parents[2] / "sjtu_tpmshx"`；兄弟导入 `predict_aircooler_10kw` 因 Python 自动把脚本所在目录加入 `sys.path[0]` 而生效。
