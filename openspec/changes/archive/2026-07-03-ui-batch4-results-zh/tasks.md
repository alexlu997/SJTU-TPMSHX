## 1. 实施 ③

- [x] 1.1 分段按钮「温度｜速度｜压力」：combo 隐藏为状态源（英文条目=内部 key 不动），按钮驱动 setCurrentIndex，currentIndexChanged 反向重绘；tab_view 门控同步 `_2d_field_seg`
- [x] 1.2 `main._copy_figure_clipboard`（active tab→canvas.grab→clipboard，无数据状态栏提示）+ 导出菜单三项中文含「复制当前图像」

## 2. 实施 ①

- [x] 2.1 中文 chrome：页签（温度/压力/速度/几何布局/优化/3D·2D 视图）、适应视图、导出 ▾、四组名、区名（域几何/TPMS 结构/几何计算值/材料属性/网格设置/网格划分/高级/流体 A·B 进出口/流体 A·B）、CTA「▶ 计算」、ticker「取消 · Ns」（startswith 守卫同步改）、自动填充 A/B、计算 TPMS 几何、预览布局 ×2、空状态+preset 按钮、onboarding、preflight 模态、`_export_figure` 选择器
- [x] 2.2 测试断言中文化 + 新增 2 测试（分段驱动/反向同步、复制无数据安全）

## 3. 验证

- [x] 3.1 UI 套件 24/24 + 真实 2D compute 截图（分段按钮就位、ticker 取消守卫、结果落地）
- [x] 3.2 全量 pytest 后台；push；归档（CI 异步）
