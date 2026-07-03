## 1. 批 1（theme + 左面板）

- [x] 1.1 theme.py：`err`/`err_soft`/`search_hl`/`title_fg` token（双主题）；RADIUS_CARD 12→6；`_frame` 8→常量；INP 内 `#DC2626/#F59E0B` → token
- [x] 1.2 field_factory：line_edit 右对齐 + `title_fg` 条件字面量归 token
- [x] 1.3 builders_domain（13pt→12）/ ui_builders（header 12→6）

## 2. 批 2（画布 + mixins + 浮层）

- [x] 2.1 builders_canvas（裸白×4→tab_on_fg、圆角 8/10→6）、command_palette、session_overview、quick_design_panel、coord_inspector、microanim（toast 调色板→token 解析，深色 glow 底与 glass_panel 同类豁免）、run_controller（pulse×2、err_soft）
- [x] 2.2 双主题截图：亮色白卡/右对齐/对比度成立；暗色回归无异常

## 3. 验证

- [x] 3.1 卫生 +3 锁（无游离卡级圆角、theme 外无裸 hex——锁测试自抓 run_controller 两处漏网、右对齐）；豁免规则成文（微型控件按比例、胶囊/toast 语义、glass_panel 暗色资产）
- [x] 3.2 全量 pytest 后台；push；归档（CI 异步）
