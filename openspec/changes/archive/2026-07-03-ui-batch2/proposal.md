# Proposal: ui-batch2

## Why

方案 2 第二批（用户确认）。勘察后诚实缩范围：原 RS-3（共享色标）**已存在**（`chk_sync_colorbar_T`）；原 RS-1（A/B 场图并排）前提不成立——域宽高比 182×42mm 使宽扁场图竖排即最优，横排会压碎纵横比。两项撤销并记录。保留三项：

1. **IA-3 CTA 搬迁**：Compute 按钮从顶栏最右（离参数区最远）**整体搬**到左面板吸底常驻条。同一 widget 对象——ticker 状态机（文本换 Cancel、点击换线）零改动；顶栏不再放 Compute（比"复制降级"方案少一套状态机同步雷区）。
2. **IA-5 首跑捷径**：空状态加"Load Shanghai preset"按钮（`_load_named_preset` 既有 builtin 机制）。
3. **RS-2-lite**：KPI 条主指标（Q/ΔP_A/ΔP_B）数值提一档字号 + accent；条已有 caption/delta 徽标结构，只动 QSS。

## Capabilities

### New Capabilities
- `ui-cta-and-shortcuts`: 吸底 CTA 常驻、空状态一键 preset、KPI 主次层级。

## Impact

- 代码：`ui/ui_builders.py`（build_param_tabs 返回 wrapper：滚动区 + 吸底条；btn_compute 迁移；顶栏移除）、`ui/builders_canvas.py`（空状态按钮 + KPI QSS）。
- 撤销记录：RS-1/RS-3 入 design（防止将来重提）。
- 前置依赖：CI Linux UI 挂死诊断修复（并行进行中，本批推送前必须解决）。
