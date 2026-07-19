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
A_LO, A_HI = 439, 853

src = open(PATH, encoding='utf-8').read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

fn = next(n for n in tree.body
          if isinstance(n, ast.FunctionDef) and n.name == '_run_3d_stack')
fn_end = fn.end_lineno

assigned_a, loaded_a = set(), set()
used_after, returns_in_a, defs_in_a = set(), [], []

class V(ast.NodeVisitor):
    def __init__(self, in_a):
        self.in_a = in_a
    def visit_Name(self, node):
        tgt = assigned_a if isinstance(node.ctx, ast.Store) else loaded_a
        if self.in_a(node.lineno):
            if isinstance(node.ctx, ast.Store):
                assigned_a.add(node.id)
            else:
                loaded_a.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            used_after.add(node.id)
        self.generic_visit(node)
    def visit_Nonlocal(self, node):
        if not self.in_a(node.lineno):
            used_after.update(node.names)
    def visit_Return(self, node):
        if self.in_a(node.lineno):
            returns_in_a.append(node.lineno)
        self.generic_visit(node)
    def visit_FunctionDef(self, node):
        if self.in_a(node.lineno):
            assigned_a.add(node.name)
            defs_in_a.append(f"{node.name}:{node.lineno}")
        self.generic_visit(node)
    def visit_Import(self, node):
        for a in node.names:
            nm = (a.asname or a.name).split('.')[0]
            (assigned_a if self.in_a(node.lineno) else set()).add(nm)
        self.generic_visit(node)
    def visit_ImportFrom(self, node):
        for a in node.names:
            nm = a.asname or a.name
            (assigned_a if self.in_a(node.lineno) else set()).add(nm)
        self.generic_visit(node)

V(lambda ln: A_LO <= ln <= A_HI).visit(fn)

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
inputs = sorted((loaded_a - assigned_a - module_names)
                - set(dir(__builtins__)) - {'cfg'})

print(f"function span: {fn.lineno}-{fn_end}")
print(f"RETURNS inside A: {returns_in_a or 'NONE'}")
print(f"nested defs in A: {defs_in_a or 'NONE'}")
print(f"BUNDLE ({len(bundle)}): {bundle}")
print(f"EXTRA INPUTS beyond cfg (must be empty): {inputs}")

if '--apply' not in sys.argv:
    sys.exit(0)
if returns_in_a:
    sys.exit('ABORT: return statements inside seam A')
if inputs:
    sys.exit(f'ABORT: extraction needs extra inputs: {inputs}')

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

tup = "(" + ",\n     ".join(bundle) + ")"
new_fn = (
    "def _build_3d_problem(cfg):\n"
    '    """Seam-A extraction (P1.5, 2026-07-20): problem setup/build --\n'
    "    profile/grid/axis-map resolution, D-F surrogate, SIMPLE A/B build,\n"
    "    initial (parallel) SIMPLE solve, LTNE input fields. Moved VERBATIM\n"
    "    from _run_3d_stack; returns the cross-seam state bundle. Contract:\n"
    "    bit-identical behavior (golden gate).\n"
    '    """\n'
    + "    # Conditionally-bound cross-seam names (surgery tool definite-\n"
    + "    # assignment pass): None-init so the unconditional return below\n"
    + "    # cannot raise UnboundLocalError on guarded paths. Downstream\n"
    + "    # reads keep their original guards.\n"
    + "".join(f"    {n} = None\n" for n in preinit)
    + "".join(lines[A_LO - 1:A_HI])
    + "\n    return " + tup + "\n\n\n"
)
call_site = "    " + tup.replace("\n     ", "\n     ") + " = _build_3d_problem(cfg)\n"

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
