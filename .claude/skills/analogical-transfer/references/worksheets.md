# Analogical-transfer worksheets

Workspace: `<out_dir>/<YYYYMMDD-HHMM>-<slug>/` with `skeleton.md`, `candidates.md`,
`mapping-<candidate>.md`, `validation.md`.

## Candidate log

```markdown
| # | Source domain | Source problem | Canonical method (citation) | Matched skeleton relations | Near/far | Found by |
|---|---|---|---|---|---|---|
| 1 | supply chains | bullwhip effect | supply-line accounting (Sterman, 1989) | R2 stale decision, R3 feedback, R1 delay | far | catalogue |
```

## Blind-retriever brief (web-searcher, MEDIUM tier)

```text
Find problems in <field family> whose STRUCTURE matches the description below. You are deliberately
not told the original domain; do not guess it, and do not return results from software operations.

Structure:
<skeleton: roles, first-order relations, higher-order relations, objective, constraints, regime>

Return up to 3 candidates, each: source field, source problem in one sentence, the field's canonical
method with one citation (URL + date or reference), and which relations of the structure it matches.
At most 12 searches (mcp__exa__web_search_exa or WebSearch). Under 250 words. Do not spawn subagents.
```

## Mapping and scoring worksheet (bullwhip example)

| # | Source relation | Target relation | Order | w | Survives | s | w x s |
|---|---|---|---|---|---|---|---|
| R1 | shipment lead time DELAYS stock arrival | pod startup DELAYS capacity | higher | 2 | yes | 1 | 2 |
| R2 | ordering on recent sales while ignoring the supply line CAUSES over-ordering | scaling on stale utilisation x current replicas CAUSES overshoot | higher | 2 | yes | 1 | 2 |
| R3 | stock level FEEDS BACK into the next order | replicas FEED BACK into measured utilisation | higher | 2 | yes | 1 | 2 |
| R4 | stock is CONSERVED (only sales remove it) | capacity can be removed instantly | higher | 2 | modified | 0.5 | 1 |
| R5 | stock SERVES demand | capacity SERVES demand | first | 1 | yes | 1 | 1 |
| R6 | returning stock is slow and costly | removing pods is fast and cheap | first | 1 | modified | 0.5 | 0.5 |

S = 8.5 / 10 = 0.85. Solution-critical relations: R1, R2, R3 (all s = 1), gate passes.

## Toy simulation used in the worked example

Stdlib Python; run with `python3 -I sim.py`. It is a model of the mechanism, not of any specific
autoscaler product; use it to check that a transferred remedy acts on the mechanism you think it does.

```python
"""Toy autoscaler: replicas r set by the controller; new pods become ready after `startup` steps;
the utilisation metric is `lag` steps stale. desired = ceil(basis * util / target)."""
import math

def run(steps=200, demand=18.0, target=0.6, startup=4, lag=3, basis="current",
        max_step=None, tolerance=0.0, stab=0, start=6):
    r = [start] * (startup + lag + 1)          # replica count history (incl. not-ready)
    hist = []
    for t in range(len(r), steps):
        ready_then = r[t - lag - startup]       # pods that were ready when the stale sample was taken
        util = min(demand / max(ready_then, 1), 1.0)
        b = r[t - 1] if basis == "current" else ready_then   # naive: stale metric x current count
        ratio = util / target
        desired = b if abs(ratio - 1) <= tolerance else math.ceil(b * ratio)
        if max_step is not None:
            desired = max(min(desired, r[t - 1] + max_step), r[t - 1] - max_step)
        hist.append(desired)
        if stab and desired < r[t - 1]:
            desired = min(max(hist[-stab:]), r[t - 1])   # scale down only to the window max
        r.append(max(desired, 1))
    return r

def show(name, r):
    tail = r[-80:]
    print("%-44s min %3d max %3d swing %3d" % (name, min(tail), max(tail), max(tail) - min(tail)))

show("naive: stale metric x current replicas", run())
show("consistent basis (replicas at sample time)", run(basis="sample"))
show("naive + step limit 2 pods", run(max_step=2))
show("naive + tolerance 0.1 + stab window 8", run(tolerance=0.1, stab=8))
print("ideal replicas:", 18 / 0.6)
```

Output (verified):

```text
naive: stale metric x current replicas       min   1 max 663 swing 662
consistent basis (replicas at sample time)   min  31 max  31 swing   0
naive + step limit 2 pods                    min  19 max  43 swing  24
naive + tolerance 0.1 + stab window 8        min   4 max 663 swing 659
ideal replicas: 30.0
```

Reading: only the bullwhip-derived remedy (consistent basis) removes the instability; the
dead-time remedy (step limit, i.e. lower gain) turns runaway into a bounded limit cycle; the
thermostat remedy (deadband plus window) does not touch the mechanism. Each prediction from
section 6 of SKILL.md was confirmed or refuted by a control run, which is what "simulated" means
on the validation ladder.

## Validation record

```markdown
| Inference | Prediction | Check | Level | Result | Evidence path |
|---|---|---|---|---|---|
| consistent basis removes overshoot | swing ~0 under steady demand | toy sim + control | simulated | confirmed | validation/sim.txt |
| same in staging | p95 replica swing < 10% over 1 h steady load | tester load test | piloted | pending | - |
```

## Adversarial brief for the top inference (adversarial-verifier)

```text
Claim: "<candidate inference>", obtained by transferring <canonical method> from <source domain>.
Mapping of solution-critical relations: <table rows>.
Try to refute it: find a relation that does not survive, a regime where it fails, or a simpler
explanation of the evidence. Default to refuted if evidence is insufficient. Return the verdict
format from adversarial-verification.
```
