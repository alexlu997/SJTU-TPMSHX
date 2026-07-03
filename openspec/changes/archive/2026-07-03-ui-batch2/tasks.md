## 1. 前置

- [x] 1.1 CI Linux UI 挂死：thread 诊断点名 `test_param_pages_have_no_horizontal_scroll`（fixture processEvents → onboarding `msg.exec()` 模态，全新 checkout 无 `.first_run_done`）；修复 = offscreen 跳过模态仍写 flag；CI 复绿 14m15s

## 2. 实施

- [x] 2.1 IA-3：btn_compute 迁入吸底条（同一对象零改线，ticker 状态机不动），header 移除；消费者 = run_controller getattr 式 + main.py 快捷键注册，均运行时安全
- [x] 2.2 IA-5：空状态容器化（`_empty_state_label` 改指容器——消费者仅 setVisible ×2，文案断言改 findChildren）；preset 按钮接 `_load_named_preset('Shanghai (3D Gyroid)')`
- [x] 2.3 RS-2-lite：Q/ΔP_A/ΔP_B 数值 chip 10pt/val 色主层；builders_canvas 死引用注释更正

## 3. 验证

- [x] 3.1 布局卫生 +3（吸底条在滚动区外、preset 点击置位 `_active_preset_name`、空状态标记），12/12；离屏真实 compute 过（ticker 恢复 + 结果落地）
- [x] 3.2 截图确认：左下常驻 CTA、顶栏 Compute 撤除、computed 卡真实流程自动展开、KPI accent 分层
- [x] 3.3 本地全量 pytest **1072 passed / 0 failed**；push 待 CI 挂死修复后合并进行
