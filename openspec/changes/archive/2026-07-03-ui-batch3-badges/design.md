# Design: ui-batch3-badges

## Context

- 逐字段校验：`main.py` `_make_validator_cb` 的 `_cb` 在 1676-1690 翻 `inpError` 动态属性（QSS 红框同源）。
- preflight（`_validate_inputs_preflight`）判坏 = `inpError=='true'` 或空文本；徽标同判据 → 徽标数 = preflight 模态行数（可见字段内）。
- 组标题现由 `_chevron_title(title, expanded)` 渲染，toggle 处重设——徽标必须并入同一渲染函数否则 toggle 抹掉徽标。
- 可见性：3D-only 行在 2D 被显式 hide。`le.isVisibleTo(content)`（content = 组内容器）忽略祖先自身可见性、只看路径上的显式 hide → 折叠组内字段仍可计数 ✓，模式门隐藏的字段不计 ✓。

## Goals / Non-Goals

**Goals:** 折叠组内问题可见；实时（编辑去抖 150ms）；语言中立 `⚠N`。
**Non-Goals:** 不替代 preflight 模态（仍是最终门）；不做逐字段跳转导航。

## Decisions

- **D1 渲染统一**：`_group_title_text(window, title)` = chevron + title + (` ⚠N` if N>0)；toggle 与 refresh 都走它。计数存 `window._group_badge_counts`。
- **D2 计数**：遍历 `_SESSION_LINE_EDITS`，`content.isAncestorOf(le)` 定组；坏 = `inpError=='true' or not text.strip()`；跳过 `not le.isVisibleTo(content)`。`window._accordion_contents[title] = content` 新登记。
- **D3 触发**：(1) `_cb` 尾部 `_badge_timer`（150ms singleShot，QTimer 挂 window）→ refresh；(2) build_param_tabs 尾部初刷；(3) 组 toggle 内复刷（模式门复断言后）。preset/undo 走 setText→textChanged→validator cb → 自动覆盖。
- **D4 门**：卫生测试 +2（清空 grid 字段→③组标题现 ⚠ 且计数≥1；修复→徽标消失）；全量 pytest；截图。

## Risks / Trade-offs

- [validator cb 未挂的字段（非 positive 集）只有空判] → 与 preflight 同行为，可接受。
- [每次刷新全字段扫描] → ~40 字段 × 属性读，微秒级，去抖后无感。
