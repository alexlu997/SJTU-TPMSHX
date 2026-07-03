## 1. 实施

- [x] 1.1 `ui_builders`：`_group_title_text` 统一渲染 + `refresh_group_badges`；`_accordion_contents` 登记；build 尾初刷；toggle 复刷
- [x] 1.2 `main.py` `_kick_badge_timer` 去抖 150ms——**必须放 `_cb` 最前**：空文本在 handler 开头早退（空值是 preflight 的职责），徽标恰恰要覆盖该情形；mock 借用 handler → getattr 守卫

## 2. 验证

- [x] 2.1 卫生测试 +3（清空→⚠；修复→消失；端到端 editingFinished→去抖；toggle 保徽标），23/23 相关绿
- [x] 2.2 带徽标截图确认；全量 pytest 后台；push；归档（CI 异步兜底）
