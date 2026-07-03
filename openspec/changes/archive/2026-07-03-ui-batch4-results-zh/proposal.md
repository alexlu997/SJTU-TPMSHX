# Proposal: ui-batch4-results-zh

## Why

用户确认"3+1 一起做"：③ 结果区细化 + ① 界面语言统一（方向定全中文——软著/组会材料均中文场景；物理符号 ε/D_h/ΔP/Nu 不翻）。

勘察后修正：③ 原第三子项"计算完成自动跳结果页签"**已存在**（`run_controller.py:603` 3D→'3d'、`:670` 2D→'temp'），撤销。

## Capabilities

### New Capabilities
- `ui-results-quickswitch`: 2D 场分段按钮单击直切 + 当前图像一键复制剪贴板。
- `ui-chinese-chrome`: 界面 chrome（按钮/页签/组名/区名/空状态/菜单）统一中文；物理量行标签与符号保持原样。

## Impact

- ③：`builders_canvas.py`（combo_2d_field 隐藏为状态源，新分段按钮驱动+反向同步；Export 菜单加"复制当前图像"）、`main.py`（`_copy_figure_clipboard`）、`tab_view.py`（门控同步分段按钮）
- ①：`builders_canvas/ui_builders/builders_domain/builders_fluids/builders_base/main.py` 文案替换；测试断言同步（`_EXPECTED_GROUPS`、空状态标记、switch_param_tab 名单）
- combo_2d_field 的英文条目文本降级为内部 key（`_resolve_2d_view_card`/`_switch_tab` 消费），不再是 UI
