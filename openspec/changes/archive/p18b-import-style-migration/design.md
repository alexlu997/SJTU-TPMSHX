# design — p18b-import-style-migration

## D1 · 为什么"身份垫片先行"而不是直接分波改写

没有垫片时，两种直觉迁移顺序都有毒：

- **先改库内**（`solvers/a.py` 内部改 `from sjtu_tpmshx.solvers.b import f`）：老式入口
  （`from solvers.x import y`）把 x 以顶层名加载，x 内部再以包名加载 b ⇒ **单条导入链内
  就产生双对象**；
- **先改调用方**（入口改 `from sjtu_tpmshx.solvers.x import y`）：x 以包名加载，其内部
  顶层风格 `from solvers.b import f` 又以顶层名加载 b ⇒ 同样双对象。

即任何"部分迁移"状态在无垫片时都等价于混用。**结论：先让两个名字指向同一对象，
迁移顺序从此不再是正确性问题**（只是工程进度问题），波次可以按目录机械推进、可以
被子代理并行执行、可以中途停摆而不留隐患。

## D2 · finder 机制（`sjtu_tpmshx/__init__.py`）

```
sys.meta_path 前插 _IdentityFinder：
  find_spec('sjtu_tpmshx.<rest>')
    ├─ <rest> 顶段 ∉ 包内实体清单 → None（放行给标准机制，如 tests/ namespace 遍历）
    └─ 否则 importlib.import_module('<rest>')       # 取/建顶层规范对象
         → spec_from_loader(fullname, _AliasLoader) # loader.create_module 返回既有对象
         → sys.modules['sjtu_tpmshx.<rest>'] 与 '<rest>' 同对象
```

要点：

- **父包 init 必先执行**（CPython 导入协议）⇒ 任何 `sjtu_tpmshx.*` 导入都先装上 finder，
  无绕过路径；
- finder **前插** sys.meta_path ⇒ 截在 PathFinder 之前，杜绝"父包 __path__ 遍历出
  第二个对象"（`import sjtu_tpmshx.solvers.x` 的机制会逐段导入，若无前插拦截，
  x 会被 PathFinder 以包名重新 exec）；
- `_AliasLoader.create_module` 返回既有模块、`exec_module` 空操作 ⇒ 模块**不会被执行
  第二次**（solvers/__init__ 的 `threads.init_from_env()` 等副作用保持单次）；
- 方向收敛：包名先导 ⇒ import_module 先把顶层键写进 sys.modules，后续顶层导入命中
  缓存；顶层先导 ⇒ import_module 直接命中缓存。**两个方向都收敛到顶层对象为规范对象**
  （与现状一致，golden 位同的前提）；
- 实体清单在 init 时从包目录**动态计算**（含 `__init__.py` 的子目录 + 顶层 .py 模块：
  solvers/pipelines/optimization/core/controllers/domain/df_surrogate/ui/runs/validation +
  cli/logutil/main/_version），`tests/` 无 init 天然除外（pytest 以顶层名导测试文件，
  别名反而制造 'tests' 这种高危通用顶层名）；
- 幂等：重复 import sjtu_tpmshx 不重复装 finder（按类型扫 meta_path）；
- 自举插 `sys.path[0]`：与现状 135 个引导块行为一致（它们也 insert(0)），不改变
  遮蔽序；风险面（'core'/'ui' 等通用名遮蔽第三方包）与现状完全相同，非新增。

## D3 · logutil 是垫片价值的实证样本

`sjtu_tpmshx/logutil.py` 维护 `tpmshx.*` logger 层级与 handler 配置。若无垫片，
`from logutil import get_logger`（库内 165 模块的现状）与 `from sjtu_tpmshx.logutil
import get_logger`（迁移后风格）各自 exec 一份 logutil ⇒ 双 handler 注册表 ⇒ 重复
日志行/丢配置，且只在混用进程里发作。warn-once 注册表（extrap/choke）同理。
身份测试直接断言这些具体对象同一。

## D4 · 波次切分与委托（PROTOCOL §10）

| 波次 | 内容 | 文件数 | 执行方 |
|---|---|---|---|
| W0 | 垫片 + 身份测试 + editable venv + openspec | 4 新增/改 | Fable 直做（本轮） |
| W1 | tests/ 迁移 | 73 | 子代理机械改，Fable 复核 |
| W2 | validation/ + df_surrogate/ | 24 | 同上 |
| W3 | runs/ + ui/ | 36 | 同上 |
| W_final | 库内 165 模块改写 + 撤垫片 + P1.5 尾巴并入 | ~165 | 子代理分批 + Fable 终审 |

每波门：全套 suite 双 pass + golden 位同 + 身份测试 + `tpmshx-run --help` exit 0 +
波内文件 `sys.path` 零残留 grep。W_final 另加：finder 撤除后全库 grep 双风格残留为零。

## D5 · 回滚

W0 可整体回滚（删 `__init__.py` + `pip uninstall sjtu-tpmshx` 回 namespace 现状，
调用方引导块未动过）。W1 起每波独立提交，git revert 波次提交即回滚该波（垫片在位
保证任意中间态安全）。

## D6 · editable install 的边界

`pip install -e . --no-deps`：venv 依赖闭包由 requirements-lock-server.txt 管理
（iter 0 精确复刻），editable 只为暴露 `sjtu_tpmshx` 包名与 console script，
**不得**触发依赖解析（--no-deps 强制）。`pip check` 必须保持无破损。
