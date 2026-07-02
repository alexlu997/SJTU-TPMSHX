## 1. 实施

- [x] 1.1 `builders_base.collapsible_section`：container 附 `_set_expanded`
- [x] 1.2 `builders_domain`：注册 8 键（含 results 摘要框——挂手风琴外常驻底部）；TPMS computed 4 行迁入"Computed geometry"折叠子区
- [x] 1.3 `builders_fluids`：注册 6 键（fluids_row/pipe_a/pipe_b/poly 两件/preview_btn）
- [x] 1.4 四组组装 + 页壳弃用（**shiboken 陷阱**：壳引用需持至重挂完成再 deleteLater，否则 C++ 子树连同 section 一起销毁）；组 toggle 复断言 dim+shape 双门；switch_param_tab 名单更新
- [x] 1.5 `main.compute_tpms` 成功尾部 `_set_expanded(True)`（守卫式）

## 2. 验证

- [x] 2.1 布局卫生测试 +5：四组默认态、左面板单滚动区、computed 折叠→算后自动展开、2D 下展开③组 Nz 不复活
- [x] 2.2 离屏截图：首屏 = ①几何/TPMS + ②流体卡，③④折叠于下方；密度显著下降；无横条/裁切
- [x] 2.3 UI 套件 64/64 + 布局卫生 8/8 绿；全量 pytest + commit/push/CI/归档
