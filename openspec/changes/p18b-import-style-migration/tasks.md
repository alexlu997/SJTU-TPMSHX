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

## W1 · tests/ 迁移（iter 44 ✓，`140166b`——实际 141 文件，非预估 73）
- [x] 删 sys.path 引导块 + 顶层导入 → `sjtu_tpmshx.*`（Sonnet 委托 + Fable 复核；
      净 -357 行）
- [x] conftest.py：引导块 → `import sjtu_tpmshx` 显式自举；ci.yml 补
      `pip install -e . --no-deps`（裸 pytest 无 cwd 于 sys.path）
- [x] 波尾 grep：残留白名单 = 身份测试（豁免）/ optionB（poc/ 引导非包）/ conftest 文档串；
      **已知余量：tests/design/ 15 文件顶层 `design` 导入（不在委托白名单）→ W_final 收**
- [x] 门禁：套件 1275+4skip / 10 绿（18:45）+ GOLDEN PASS 位同（判定行核实）

## W2 · validation/ + df_surrogate/ 全目录迁移（iter 45 ✓，`59ee773`——31/44 文件）
- [x] 逐文件手改（W1 行尾教训内化）；3 逃生舱有据（script-dir insert 兄弟脚本互导）；
      13 文件零改动有据；自伤两处自查修复（3 文件整文件行尾翻转字节级抓获 / 孤儿 Path）
- [x] 门禁：套件 1275+4skip / 10 绿（19:08）+ GOLDEN PASS 位同 + Shanghai 冒烟
      **GATE PASS headline 位同**（4.88%/2.12%）+ tracked CSV ULP 自改写回退（1.4e-12）

## W3 · runs/ + ui/demo_vis_3d 迁移（iter 46 ✓，`1f0e689`——32 文件，零逃生舱）
- [x] golden 门脚本本体随波迁移（__main__ 守卫核实）；archive/ 零 diff；--help 抽 5 冒烟；
      AST 遍历残留双保险全零；自伤 1（孤儿 import，被套件内 lint 门实战拦截）
- [x] 门禁：套件 1275+4skip / 10 绿（18:52）+ GOLDEN PASS 位同（=迁移后门脚本自跑）

## W_final-F1 · 库内改写（iter 47 ✓，`d672eba`——78 文件 339 行纯替换）
- [x] AST 列级改写（方法终态：ast 节点列定位+纯插入）；相对导入不动；design 余量清账；
      cli.py/main.py 双约定支持件有据跳过 → F2 正题；分析器本就双约定兼容免修
- [x] 门禁：套件 1275+4skip / 10 绿（19:13）+ GOLDEN PASS 位同 + type gate 绿
      （预判 found-twice 未发生）

## W_final-F2 · 撤垫片收官
- [ ] 全库双风格残留 grep 零核对 → 撤 _IdentityFinder 与自举；`__init__.py` 瘦身为普通包 init
- [ ] cli.py/main.py 双约定引导块改造（撤垫片后包名风格为唯一约定）
- [ ] P1.5 尾巴并入：run_stack_3d 五阶段函数 → `run_stack_3d_stages.py`（保 re-export 面）
- [ ] pyproject 头注收尾；atlas repo-infra / pipelines 卷收编注记
- [ ] 全库 grep：双风格残留零、sys.path 引导仅存钦定白名单（若有）
- [ ] 门禁全套 + golden 位同 + 身份测试改为"垫片已撤"断言
