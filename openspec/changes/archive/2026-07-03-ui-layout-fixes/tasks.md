## 1. 实施

- [x] 1.1 `FieldFactory.label()` wordWrap 默认 ON（单点全局生效）；左面板外层 + domain/fluids/zones 四处 QScrollArea 横条 AlwaysOff
- [x] 1.2 `ui/responsive.py::ResponsiveRow` + `builders_fluids` 接入；实测默认窗宽下该行仅得 521px → 阈值 520 擦线并排挤压，提至 640（每卡 ~310px 呼吸位），spec 同步修订
- [x] 1.3 空状态三步引导（标题 + 编号 accent + 动词开头文案 + Ctrl+R 提示）

## 2. 验证

- [x] 2.1 `tests/test_ui_layout_hygiene.py` 4 测试（横条零溢出、_fluids_row 类型、独立实例方向翻转——布局管理下 widget 不可自由 resize、空状态三步标记）
- [x] 2.2 离屏截图前后对比：卡内横条消失、输入裁切修复、标签折行、双卡竖排、空状态结构化——全部结构级可见
- [x] 2.3 离屏 UI pytest 26/26 绿 + 全量 pytest；commit + push + CI；归档
