# SCCP on a toy SSA IR: implementation and golden tests

Companion to section 13 of the skill. Plain Python 3.10+, no dependencies; run with
`uv run --python 3.13 python -m pytest sccp_toy.py` (or any pytest).

## IR

A program maps block names to instruction tuples. Operands are SSA names (strings) or integer
literals.

| Tuple | Meaning |
|---|---|
| `("const", dst, k)` | `dst = k` |
| `("add" / "mul" / "lt", dst, a, b)` | arithmetic and comparison (`lt` yields 0 or 1) |
| `("call", dst, fn)` | opaque call: never a constant |
| `("phi", dst, {pred: name})` | SSA phi |
| `("br", cond, then_blk, else_blk)`, `("jmp", blk)`, `("ret", name)` | terminators |

## sccp_toy.py

```python
"""Sparse conditional constant propagation (Wegman and Zadeck, 1991) on a toy SSA IR."""
from collections import defaultdict

TOP, BOT = "top", "bottom"      # TOP: no information yet (optimistic); BOT: not a constant
OPS = {"add": lambda x, y: x + y, "mul": lambda x, y: x * y, "lt": lambda x, y: int(x < y)}


def meet(a, b):
    if a == TOP:
        return b
    if b == TOP or a == b:
        return a
    return BOT


def operands(ins):
    op = ins[0]
    if op in OPS:
        names = [ins[2], ins[3]]
    elif op == "phi":
        names = list(ins[2].values())
    elif op in ("br", "ret"):
        names = [ins[1]]
    else:
        names = []
    return [n for n in names if isinstance(n, str)]


def sccp(blocks, entry="entry"):
    uses = defaultdict(list)                      # SSA edges: name -> [(block, instruction)]
    for b, body in blocks.items():
        for ins in body:
            for name in operands(ins):
                uses[name].append((b, ins))
    val = defaultdict(lambda: TOP)
    edges, reached = set(), set()                 # executable CFG edges and blocks
    cfg_work, ssa_work = [entry], []

    def get(x):
        return x if isinstance(x, int) else val[x]

    def lower(name, new):                         # values only move down the lattice
        if new != val[name]:
            val[name] = new
            ssa_work.extend(uses[name])

    def add_edge(src, dst):
        if (src, dst) not in edges:
            edges.add((src, dst))
            cfg_work.append(dst)

    def visit(b, ins):
        op = ins[0]
        if op == "const":
            lower(ins[1], ins[2])
        elif op == "call":
            lower(ins[1], BOT)
        elif op == "phi":                         # meet over executable incoming edges only
            v = TOP
            for pred, name in ins[2].items():
                if (pred, b) in edges:
                    v = meet(v, get(name))
            lower(ins[1], v)
        elif op in OPS:
            x, y = get(ins[2]), get(ins[3])
            lower(ins[1], BOT if BOT in (x, y) else TOP if TOP in (x, y) else OPS[op](x, y))
        elif op == "br":
            c = get(ins[1])
            if c == BOT:
                add_edge(b, ins[2])
                add_edge(b, ins[3])
            elif c != TOP:
                add_edge(b, ins[2] if c else ins[3])
        elif op == "jmp":
            add_edge(b, ins[1])

    while cfg_work or ssa_work:
        if cfg_work:
            b = cfg_work.pop()
            first = b not in reached
            reached.add(b)
            for ins in blocks[b]:
                if first or ins[0] == "phi":      # a new edge can change only the phis
                    visit(b, ins)
        else:
            b, ins = ssa_work.pop()
            if b in reached:                      # ignore uses in unreachable blocks
                visit(b, ins)
    return val, edges, reached


def rewrite(blocks, val, edges, reached):
    out = {}
    for b, body in blocks.items():
        if b not in reached:
            continue                              # unreachable block: delete
        new = []
        for ins in body:
            op = ins[0]
            known = len(ins) > 1 and isinstance(ins[1], str) and val[ins[1]] not in (TOP, BOT)
            if op == "br" and known:
                new.append(("jmp", ins[2] if val[ins[1]] else ins[3]))
            elif op in ("const", "phi", *OPS) and known:
                new.append(("const", ins[1], val[ins[1]]))
            elif op == "phi":
                new.append(("phi", ins[1], {p: n for p, n in ins[2].items() if (p, b) in edges}))
            else:
                new.append(ins)
        out[b] = new
    return out


def show(blocks):
    lines = []
    for b, body in blocks.items():
        lines.append(f"{b}:")
        for ins in body:
            op = ins[0]
            if op == "const":
                lines.append(f"  {ins[1]} = const {ins[2]}")
            elif op in OPS:
                lines.append(f"  {ins[1]} = {op} {ins[2]}, {ins[3]}")
            elif op == "call":
                lines.append(f"  {ins[1]} = call {ins[2]}")
            elif op == "phi":
                args = ", ".join(f"[{p}: {n}]" for p, n in ins[2].items())
                lines.append(f"  {ins[1]} = phi {args}")
            elif op == "br":
                lines.append(f"  br {ins[1]}, {ins[2]}, {ins[3]}")
            else:
                lines.append(f"  {op} {ins[1]}")
    return "\n".join(lines) + "\n"


PROG = {
    "entry": [("const", "x0", 4), ("lt", "c0", "x0", 10), ("br", "c0", "then", "else")],
    "then": [("add", "y1", "x0", 1), ("jmp", "join")],
    "else": [("call", "y2", "f"), ("jmp", "join")],
    "join": [("phi", "y3", {"then": "y1", "else": "y2"}), ("ret", "y3")],
}

GOLDEN = """\
entry:
  x0 = const 4
  c0 = const 1
  jmp then
then:
  y1 = const 5
  jmp join
join:
  y3 = const 5
  ret y3
"""


def test_folds_branch_phi_and_deletes_dead_block():
    val, edges, reached = sccp(PROG)
    assert ("entry", "else") not in edges and "else" not in reached
    assert val["y3"] == 5 and val["y2"] == TOP    # y2 never evaluated: its block is dead
    assert show(rewrite(PROG, val, edges, reached)) == GOLDEN


def test_unknown_condition_keeps_both_paths():
    prog = dict(PROG, entry=[("call", "x0", "g"), ("lt", "c0", "x0", 10), ("br", "c0", "then", "else")])
    val, edges, reached = sccp(prog)
    assert {("entry", "then"), ("entry", "else")} <= edges
    assert val["y3"] == BOT                       # meet of BOT (call) with anything


def test_loop_reaches_fixpoint():
    prog = {
        "entry": [("const", "i0", 0), ("jmp", "head")],
        "head": [("phi", "i1", {"entry": "i0", "body": "i2"}), ("lt", "c", "i1", 3), ("br", "c", "body", "exit")],
        "body": [("add", "i2", "i1", 1), ("jmp", "head")],
        "exit": [("ret", "i1")],
    }
    val, _, _ = sccp(prog)
    assert val["i1"] == BOT                       # 0 meets 1 at the loop header
```

## Golden-file workflow

- Keep `GOLDEN` in a file next to the test (`tests/golden/sccp_toy.ir`) once there are more than a
  few cases; regenerate with an explicit flag (`UPDATE_GOLDEN=1`) and review the diff like code.
- Snapshot tooling does the same job: insta in Rust (`cargo insta review`), syrupy for pytest.
- Add a differential test: interpret the program before and after `rewrite` on random inputs (for
  programs with parameters) and compare results. It catches rewrites that are wrong rather than
  merely different.

## Extensions worth the next hour

- Fold uses: substitute constants into operands (`ret 5`), then run DCE on unused definitions.
- Loops: SCCP gives up on induction variables (the loop test above ends with `i1` at BOT); interval
  analysis with widening, or unrolling, is the next tool for bounds and trip counts.
- Integer semantics: model wrap-around for fixed-width types (mask after `add` and `mul`); for an
  LLVM-style IR, treat `nsw`/`nuw` overflow as poison rather than folding through it.
