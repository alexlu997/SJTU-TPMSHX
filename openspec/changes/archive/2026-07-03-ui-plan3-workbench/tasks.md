## 1. T1 页签收敛

- [x] 1.1 工具条 [几何布局][结果][字段段控][优化] + 右端 [2D|3D][复制图像][适应视图][导出]；legacy 五钮离条存活
- [x] 1.2 'result' 聚合解析（复用 '2d_view' 模式）+ 反向同步 + 分屏解析 + 门控（rules['result']、段控双侧独立、唯一可用侧自动吸附）
- [x] 1.3 锁测试 ×3。坑：`_has_results_2d` 是 ResultCache 属性桥（写 True no-op）→ 测试喂 `cache.set_result`；模块级 fixture 里 preset 测试遗留 3D 模式 → 显式置回

## 2. T2 侧栏

- [x] 2.1 canvas HBox + 298px 侧栏三卡（本次结果/可信度/收敛）；`_res_bar` 退役为数据载体；Sparkline 复用 optimize 控件
- [x] 2.2 `_diag_summary` 在 write_result 顶部统一落（3D 早退前）；收敛历史直读 `_live_residuals['A']`（游标排水不清列表，天然全程累积）
- [x] 2.3 真实 compute 截图 + 断言（侧栏随页签显隐、KPI 落值、闭合徽标、横带隐藏）

## 3. T3 诊断对话框

- [x] 3.1 `_show_diag_dialog` + `_diag_summary_text`（能量对账/系数/迭代/警告/外推，一键复制）
- [x] 3.2 全量 pytest 后台；push；归档（CI 异步）
