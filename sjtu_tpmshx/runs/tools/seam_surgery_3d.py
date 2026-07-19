"""Seam-A analysis + surgery for run_stack_3d.py (P1.5 iter 12).

Phase 1 (always): AST name-flow analysis of _run_3d_stack over the splice
range [A_LO, A_HI] (1-based, inclusive) — reports the state bundle
(assigned-in-A and referenced-after), the required inputs, and safety checks
(no `return` inside A; nested defs inside A listed).

Phase 2 (--apply): textual surgery — move the lines verbatim into a new
module-level function `_build_3d_problem(cfg)` inserted above _run_3d_stack,
replace the region with a generated tuple-unpack call. Tuple order comes from
ONE list shared by both ends, so no transcription drift is possible.
"""
import ast
import sys

PATH = r'E:\LWH\SJTU-TPMSHX-upgrade\sjtu_tpmshx\pipelines\run_stack_3d.py'
A_LO, A_HI = 2271, 2671
NEW_NAME = '_assemble_3d_verdict'

src = open(PATH, encoding='utf-8').read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

fn = next(n for n in tree.body
          if isinstance(n, ast.FunctionDef) and n.name == '_run_3d_stack')
fn_end = fn.end_lineno

assigned_a, loaded_a = set(), set()
used_after, returns_in_a, defs_in_a = set(), [], []


def _fn_locals(fnode):
    """Names bound anywhere inside fnode (params + stores + inner defs +
    imports). Over-broad (treats inner-def locals as fnode-local) — safe
    for free-variable EXCLUSION."""
    s = {a.arg for a in fnode.args.args + fnode.args.kwonlyargs}
    if fnode.args.vararg:
        s.add(fnode.args.vararg.arg)
    if fnode.args.kwarg:
        s.add(fnode.args.kwarg.arg)
    for n in ast.walk(fnode):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            s.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.Lambda)) and n is not fnode:
            if isinstance(n, ast.FunctionDef):
                s.add(n.name)
            for a in n.args.args + n.args.kwonlyargs:
                s.add(a.arg)
            if n.args.vararg:
                s.add(n.args.vararg.arg)
            if n.args.kwarg:
                s.add(n.args.kwarg.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                s.add((a.asname or a.name).split('.')[0])
    return s


def _fn_free_loads(fnode):
    loc = _fn_locals(fnode)
    free = {n.id for n in ast.walk(fnode)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            and n.id not in loc}
    # nonlocal names are free by definition (they bind to the enclosing
    # scope even though the def also Stores them locally).
    for n in ast.walk(fnode):
        if isinstance(n, ast.Nonlocal):
            free.update(n.names)
    return free


# Scope-aware region pass over _run_3d_stack's TOP-LEVEL statements.
for st in fn.body:
    in_a = A_LO <= st.lineno <= A_HI
    if isinstance(st, ast.FunctionDef):
        if in_a:
            assigned_a.add(st.name)
            defs_in_a.append(f"{st.name}:{st.lineno}")
            loaded_a |= _fn_free_loads(st)
        else:
            used_after |= (_fn_free_loads(st)
                           if st.lineno > A_HI else set())
            for n in ast.walk(st):
                if isinstance(n, ast.Nonlocal) and st.lineno > A_HI:
                    used_after.update(n.names)
        continue
    for n in ast.walk(st):
        if isinstance(n, ast.FunctionDef):
            # non-def top statement can't nest defs except lambdas; guard
            continue
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            # x += y both LOADS and STORES x, but the AST carries only a
            # Store ctx on the target — record the load half explicitly.
            if in_a:
                assigned_a.add(n.target.id)
                loaded_a.add(n.target.id)
            elif st.lineno > A_HI:
                used_after.add(n.target.id)
        if isinstance(n, ast.Name):
            if in_a:
                (assigned_a if isinstance(n.ctx, ast.Store)
                 else loaded_a).add(n.id)
            elif st.lineno > A_HI and isinstance(n.ctx, ast.Load):
                used_after.add(n.id)
        elif isinstance(n, ast.Return) and in_a:
            returns_in_a.append(n.lineno)
        elif isinstance(n, (ast.Import, ast.ImportFrom)) and in_a:
            for a in n.names:
                assigned_a.add((a.asname or a.name).split('.')[0])

module_names = set()
for n in tree.body:
    for sub in ast.walk(n) if not isinstance(n, ast.FunctionDef) else [n]:
        if isinstance(sub, ast.FunctionDef) or isinstance(sub, ast.ClassDef):
            module_names.add(sub.name)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            module_names.add(sub.id)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for a in sub.names:
                module_names.add((a.asname or a.name).split('.')[0])

bundle = sorted(assigned_a & used_after)
# Execution-order first-occurrence scan over the region's TOP-LEVEL
# statements: a name whose FIRST top-level occurrence is a Load is an
# in(-out) parameter even if the region later rebinds it (the
# load-then-store case: e.g. `x.append(...)` ... `x = dedup(x)`).
first_kind = {}


def _note_first(nm, kind):
    if nm not in first_kind:
        first_kind[nm] = kind


def _scan_store_t(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            _note_first(n.id, 'store')


def _scan_order(node, suppress=frozenset()):
    if isinstance(node, ast.FunctionDef):
        _note_first(node.name, 'store')
        return
    if isinstance(node, ast.Lambda):
        return
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                         ast.DictComp)):
        comp_locals = set(suppress)
        for g in node.generators:
            _scan_order(g.iter, frozenset(comp_locals))
            comp_locals |= {n.id for n in ast.walk(g.target)
                            if isinstance(n, ast.Name)}
        rest = ([node.key, node.value] if isinstance(node, ast.DictComp)
                else [node.elt])
        for g in node.generators:
            rest += list(g.ifs)
        for r_ in rest:
            _scan_order(r_, frozenset(comp_locals))
        return
    if isinstance(node, ast.Assign):
        _scan_order(node.value, suppress)
        for t in node.targets:
            _scan_store_t(t)
        return
    if isinstance(node, ast.AugAssign):
        _scan_order(node.value, suppress)
        if isinstance(node.target, ast.Name):
            _note_first(node.target.id, 'load')
            _note_first(node.target.id, 'store')
        return
    if isinstance(node, ast.AnnAssign):
        if node.value is not None:
            _scan_order(node.value, suppress)
        _scan_store_t(node.target)
        return
    if isinstance(node, ast.For):
        _scan_order(node.iter, suppress)
        _scan_store_t(node.target)
        for b in node.body + node.orelse:
            _scan_order(b, suppress)
        return
    if isinstance(node, ast.Name):
        if node.id not in suppress:
            _note_first(node.id,
                        'load' if isinstance(node.ctx, ast.Load) else 'store')
        return
    for ch in ast.iter_child_nodes(node):
        _scan_order(ch, suppress)


for st in fn.body:
    if A_LO <= st.lineno <= A_HI:
        _scan_order(st)

closure_free = set()
for st in fn.body:
    if A_LO <= st.lineno <= A_HI and isinstance(st, ast.FunctionDef):
        closure_free |= _fn_free_loads(st)
inputs = sorted((({n for n, k2 in first_kind.items() if k2 == 'load'}
                  | (closure_free - assigned_a))
                 - module_names - set(dir(__builtins__)) - {'cfg'}))

print(f"function span: {fn.lineno}-{fn_end}")
print(f"RETURNS inside A: {returns_in_a or 'NONE'}")
print(f"nested defs in A: {defs_in_a or 'NONE'}")
print(f"BUNDLE ({len(bundle)}): {bundle}")
print(f"EXTRA INPUTS beyond cfg (must be empty): {inputs}")

if '--apply' not in sys.argv:
    sys.exit(0)
if returns_in_a:
    sys.exit('ABORT: return statements inside the seam')
# Seam B: nested defs are the POINT (closures become factory-made callables),
# and extra inputs become the factory signature.

# Definite-assignment at the A block's TOP statement level: names bound by an
# unconditional top-level statement are safe; everything else (bound only
# inside if/for/try) must be pre-initialized to None, or the unconditional
# return tuple raises UnboundLocalError on paths the original code guarded.
definite = set()
for st in fn.body:
    if not (A_LO <= st.lineno <= A_HI):
        continue
    if isinstance(st, ast.Assign):
        for t in st.targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    definite.add(n.id)
    elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
        definite.add(st.target.id)
    elif isinstance(st, (ast.Import, ast.ImportFrom)):
        for a in st.names:
            definite.add((a.asname or a.name).split('.')[0])
    elif isinstance(st, ast.FunctionDef):
        definite.add(st.name)
params = {a.arg for a in fn.args.args}
preinit = sorted(set(bundle) - definite - params)
print(f"PRE-INIT (conditionally bound, {len(preinit)}): {preinit}")

sig = ", ".join(inputs + ['cfg'] if 'cfg' in loaded_a else inputs)
tup = "(" + ",\n     ".join(bundle) + ")"
new_fn = (
    f"def {NEW_NAME}({sig}):\n"
    '    """Seam-E extraction (P1.5, 2026-07-20): verdict + assembly tail --\n'
    "    conservation diagnostics, post-solve envelope gate, convergence\n"
    "    verdict/truth table, result-dict assembly, opt-in audit exports.\n"
    "    Moved VERBATIM from _run_3d_stack; returns the cross-seam\n"
    "    bundle. Contract: bit-identical behavior (golden gate).\n"
    '    """\n'
    + "    # Conditionally-bound cross-seam names (surgery tool definite-\n"
    + "    # assignment pass): None-init so the unconditional return below\n"
    + "    # cannot raise UnboundLocalError on guarded paths. Downstream\n"
    + "    # reads keep their original guards.\n"
    + "".join(f"    {n} = None\n" for n in preinit)
    + "".join(lines[A_LO - 1:A_HI])
    + "\n    return " + tup + "\n\n\n"
)
call_site = ("    " + tup.replace("\n     ", "\n     ")
             + f" = {NEW_NAME}({sig})\n")

def_line = fn.lineno  # 'def _run_3d_stack' line, 1-based
out = (lines[:def_line - 1]
       + [new_fn]
       + lines[def_line - 1:A_LO - 1]
       + [call_site]
       + lines[A_HI:])
new_src = "".join(out)
compile(new_src, PATH, 'exec')
open(PATH, 'w', encoding='utf-8', newline='').write(new_src)
print("APPLIED: syntax OK, file written")
