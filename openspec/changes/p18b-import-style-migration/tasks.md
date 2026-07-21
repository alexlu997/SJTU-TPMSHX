# Tasks — p18b-import-style-migration

## W0 · 身份垫片 + editable 地基（iter 43 ✓）
- [x] `sjtu_tpmshx/__init__.py`：自举 + _IdentityFinder（前插 meta_path，幂等按类属性
      标记判重——reload 后 isinstance 失效实测坑；exec_module 恢复规范 __spec__/__loader__
      ——import 机制改绑实测坑）
- [x] `tests/test_import_identity_shim.py`：7 断言（双风格同对象 / 深层 / 注册表共享 /
      幂等 / 模块体不重执行 / spec 存续 / tests 不别名）
- [x] `pip install -e . --no-deps` + `pip check` 无破损 + `tpmshx-run --help` exit 0
      + 包外 cwd 身份成立
- [x] pyproject.toml 头注改写 + `[tool.mypy] explicit_package_bases = true`
      （新 __init__ 使 mypy 上溯出双模块名 "found twice"——首轮门红根因；cwd 基底
      与 W0 前语义位同，W_final 换仓库根基底）
- [x] 门禁：全套 1275+4skip / 10 绿（18:57）+ golden PASS 位同（日志 upgrade/logs/iter43-*；
      注意 golden 单跑时 PS 5.1 stderr 包装会假红退出码，以判定行为准）

## W1 · tests/ 迁移（73 文件，§10 委托）
- [ ] 删各文件 sys.path 引导块；顶层导入 → `sjtu_tpmshx.*`
- [ ] conftest.py 同波处理；波尾 grep：tests/ 内 `sys.path` 零残留
- [ ] 门禁全套

## W2 · validation/（17）+ df_surrogate/（7）迁移（§10 委托）
- [ ] 同 W1 流程；validation 侧注意 gate 脚本可独立直跑（`python -u` 入口语义不变）
- [ ] 门禁全套 + validate_shanghai_3d_real gate 脚本冒烟

## W3 · runs/（35）+ ui/（1）迁移（§10 委托）
- [ ] 同 W1 流程；runs/ 直跑脚本逐个 `--help`/dry 冒烟；archive/ 冻结区只注记不迁移
- [ ] 门禁全套

## W_final · 库内改写 + 撤垫片
- [ ] 库内 165 模块 `from solvers...` 等 → `from sjtu_tpmshx....`（子代理分批）
- [ ] 撤 _IdentityFinder 与自举；`__init__.py` 瘦身为普通包 init
- [ ] P1.5 尾巴并入：run_stack_3d 五阶段函数 → `run_stack_3d_stages.py`（保 re-export 面）
- [ ] pyproject 头注收尾；atlas repo-infra / pipelines 卷收编注记
- [ ] 全库 grep：双风格残留零、sys.path 引导仅存钦定白名单（若有）
- [ ] 门禁全套 + golden 位同 + 身份测试改为"垫片已撤"断言
