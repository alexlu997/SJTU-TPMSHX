# nTop graded-TPMS workflow — 从优化结果到打印件 STL

**日期**: 2026-05-08
**作者**: Claude (与 alexlu997 协作)
**关联代码**: `optimization/export_ntop_csv.py`

## 0. 总览

闭环: **qNEHVI Pareto → 选 1 个候选 → 导 ScalarField CSV → nTop GUI 装配 Walled TPMS → 切外形 → 出 STL → 打印**。

## 1. 申请 nTop Education License

[必做, 阻塞步]

- 入口: https://www.ntop.com/resources/ntop-education-portal/
- 备选: 邮 student@ntop.com, 附 SJTU 在读证明
- SJTU 邮箱 `.edu.cn` 域名一般 24-48 工作时批
- 教师 (导师) 可申 Site License 覆盖整组, 自动覆盖学生

## 2. 硬件确认

- Windows 10/11 64-bit (Linux/Mac 不支持)
- RAM ≥ 32 GB (推 64; graded-TPMS 大模型吃 16-30 GB)
- GPU NVIDIA RTX/Quadro, ≥ 8 GB VRAM
- SSD ≥ 200 GB free

## 3. 选 Pareto 候选 + 导出 CSV

```bash
# 例: 从 production_v1 Pareto 取第 7 行 (按 Q 升序排第 7), 导出到 nTop_inputs/case_7
python -m optimization.export_ntop_csv \
    --pareto opt_runs/production_v1/pareto_final.csv \
    --row    7 \
    --out    nTop_inputs/case_7 \
    --grid   100 50
```

输出 (`nTop_inputs/case_7/`):
- `Lfield.csv` — `x_mm, y_mm, L_mm` × (Nx · Ny) 行
- `tfield.csv` — `x_mm, y_mm, t_mm` × (Nx · Ny) 行
- `provenance.json` — 决策向量 + 字段统计 + 源 CSV 引用

## 4. nTop GUI 流程 (v4.x / v5.x)

### Step 4.1 — 启动 + 创建项目

1. `File → New` 空白项目
2. `Add → Variable → ScalarField` × 2 (一个给 L, 一个给 t)

### Step 4.2 — 导入 ScalarField CSV

对 L, t 各做一次:

1. `Add → Block → Scalar Field from Grid Data`
2. Inputs:
   - **Grid Data**: 浏览到 `Lfield.csv` (或 `tfield.csv`)
   - **Header Row**: 1 (跳过 `x_mm,y_mm,L_mm` 那行)
   - **X Column**: 1 (即 x_mm)
   - **Y Column**: 2 (即 y_mm)
   - **Z Column**: -1 (无 z, 二维场)
   - **Value Column**: 3
   - **Units**: `mm` (默认)
3. 命名为 `L_field` / `t_field`

**注意**: nTop 默认 ScalarField 单位是 mm; 若你的项目用 m, 在 `Plot Field` 时检查刻度。

### Step 4.3 — 创建 Walled TPMS 实体

1. `Add → Block → Body from Walled TPMS` (或 nTop 5.x 的 `Periodic Surface Lattice`)
2. Inputs:
   - **Cell Type**: `Schwarz Diamond` (与你优化用的一致)
   - **Cell Size**: 接 `L_field` ScalarField (★ nTop 杀手锏: cell size 可以是空间变化场)
   - **Wall Thickness**: 接 `t_field`
   - **Approximation Bounds**: HX 包络 box (见 4.4)
   - **Approximation Tolerance**: 0.05 mm (起步)
3. 命名 `tpms_body`

nTop 内部自动做相位场积分 (phase-coherent graded TPMS), 不需要你写公式。

### Step 4.4 — 创建 HX 外形包络

1. `Add → Block → Body from Box`
2. Inputs:
   - **Origin**: `(0, 0, 0)` mm
   - **Length X**: 100 mm (= L_domain)
   - **Length Y**: 50 mm (= H_domain)
   - **Length Z**: 20 mm (= 你的 HX 深度, 与 cfg['Lz'] 对应)
3. 命名 `hx_envelope`

### Step 4.5 — Boolean 切割 + 进出口 manifold (可选)

1. `Add → Block → Boolean Intersect`
   - **Operands**: `tpms_body` ∩ `hx_envelope`
2. 若有进出口 manifold 实心:
   - 单独建 `inlet_block` / `outlet_block` (Box)
   - `Boolean Union` 加进 TPMS body

### Step 4.6 — 输出 STL (打印用)

1. `Add → Block → Surface Mesh Body`
2. Inputs:
   - **Body**: 上一步的 Boolean 结果
   - **Edge Length**: 0.1-0.2 mm (打印 SLM 推荐 0.15)
   - **Approximation Tolerance**: 0.05 mm
3. `Right-click → Export → STL`
4. 保存 `case_7_diamond_graded.stl`

### Step 4.7 — 输出 .inp / .nas (3D CFD 验证用)

1. `Add → Block → Volume Mesh Body`
2. **Mesh Type**: Tet 4-node (与 ANSYS/Abaqus 兼容)
3. **Edge Length**: 0.3-0.5 mm (粗于 STL, 节省内存)
4. Export → `.inp` 给 Abaqus / `.nas` 给 ANSYS

## 5. 坑 + 调试

| 现象 | 可能原因 | 修法 |
|---|---|---|
| `Cell Size` 字段被 nTop 钳到下限 | L_field 值 < 0.5 mm | 检查 export CSV: `head Lfield.csv` 看 L 范围 |
| 边界处 t 显示 < t_min | Boolean 截切薄壁 | 在 `Walled TPMS` 之前加 `Offset Body` 0.5 mm |
| Mesh 三角面爆 (>10⁵) | edge_length 过细 | 加大到 0.3 mm, 或改用 Adaptive |
| 大模型导出慢/挂 | RAM 吃完 | 分块 Boolean (HX 切 4 段), 或降 approx_tol |
| TPMS 表面有撕裂 | cell size 梯度太陡 | 检查 `provenance.json` 的 L 梯度; manufacturability_penalty 应该已经过滤掉 |
| nTop 找不到 ScalarField from Grid Data | 版本太旧 | 至少 nTop 4.5+; 老版叫 `Scalar Field from Points` |

## 6. 闭环验证 (推荐做)

导完 STL 后:
1. 用 `Volume Mesh Body` 出 `.vtk` / `.cgns`
2. 喂回 OpenFOAM 或 ANSYS Fluent 做独立 3D CFD
3. 比较实测 Q / dP 与优化器预测值
   - 优化预测来自 ConstDF-v1 surrogate + SIMPLE 2D
   - 独立 3D CFD 是真值
4. 误差 < 10% 即视为闭环成功

预期: Q 误差 ~5-10%, dP 误差 ~15-25% (与 Shanghai 38% baseline 量级一致, 但优化结果在 surrogate 训练窗内, 应明显更好)

## 7. 论文 figure 模板

建议 figure 4-6 panel:
1. (a) Pareto 前沿 (Q vs dP), 标 baseline + 选定候选点
2. (b) 选定候选的 L(x,y) heatmap
3. (c) 选定候选的 t(x,y) heatmap
4. (d) nTop 渲染的 graded TPMS 切片 (showing 周期变化)
5. (e) 3D 渲染整体 HX
6. (f) 独立 CFD 验证: 3D temperature 切片 (Ta, Tb, Ts)

## 8. 后续路径

- B 完成后, 若 nTop license 没批, 可用 MSLattice (Matlab) 做 backup
- 或写 Python implicit pipeline (skimage marching_cubes) 自主可控但烂尾
- 论文最佳: 主图 nTop, 附录 Python pipeline 作 reproducibility
