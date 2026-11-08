---
name: ensemble-assembly
description: "Assembling expert ensembles: decomposing a problem into load-bearing sub-questions and disciplines, selecting 2-7 expert agents with explicit roles (lead, specialist, challenger, integrator), diversity via agent tiers and framings, a shared glossary and answer interface, scoped briefs, concurrent or two-wave execution, and the handoff to synthesis, mediation, Delphi or debate. Load when a problem spans several disciplines."
when_to_use: "When one answer needs several kinds of expertise at once (e.g. numerics plus systems plus performance, physics plus graphics, security plus protocol design), when choosing which experts to involve and why, or when writing briefs for a multi-expert team."
---

# Ensemble assembly

An ensemble is a temporary team of experts whose answers are **complementary pieces** of one
solution. The assembler's value is in three decisions: which sub-questions actually carry the answer,
who owns each one, and what shape each answer must have so they can be integrated without guesswork.
If the experts would be answering the SAME question competitively, you want a mediator vote instead
(see `orchestration-patterns`).

Full roster with defaults, strengths and authority overlaps: [roster matrix](references/roster-matrix.md).
A complete ENSEMBLE.md manifest and briefs for a real case: [ensemble example](references/ensemble-example.md).

## 1. Procedure

1. **Frame**: restate the problem as an outcome plus checkable acceptance criteria. Ambiguous
   outcome with high cost of guessing: return a scope doubt to the caller before assembling anyone.
2. **Decompose** into sub-questions SQ1..SQn (section 2). Mark each load-bearing or not.
3. **Map** each load-bearing SQ to one owning discipline and agent (section 3).
4. **Size and assign roles** (section 4). 2-7 members. Exactly one lead.
5. **Plan diversity** (section 5): agent tiers, framings.
6. **Write the manifest** `ENSEMBLE.md` with glossary, shared assumptions and the answer interface
   (section 6).
7. **Brief** each member (section 7). Paths, not pasted content.
8. **Run** in one wave, or two waves when members depend on the lead's skeleton (section 8).
9. **Check returns** against the interface; patch gaps with one retry or a narrow follow-up.
10. **Hand off** to integration (section 9) and return the roster with reasons, the integrated result
    path, and dissent.

## 2. Decomposition into disciplines

For each candidate sub-question ask three things:

| Test | Question | Consequence |
|------|----------|-------------|
| Ownership | Whose professional mistake would it be if this answer were wrong? | That discipline owns it |
| Load-bearing | If this SQ were answered wrong, would the final answer change materially? | No -> fold into another member's scope or answer it yourself |
| Dependency | Does this SQ need another SQ's answer first? | Yes -> two waves, or state the interface need in both briefs |

Signals of a missing discipline: a term you cannot define with units; a constraint type nobody owns
(security, numerics, latency, regulatory, UX, operations); an estimate with no owner; a failure mode
nobody on the roster would recognise. Add the discipline or record it as an Open doubt; never let the
integrator discover it.

Worked decomposition, "port a Julia stiff ODE solver to no_std Rust for an embedded controller,
results within 1e-8 relative error of the reference, 1 kHz control loop":

| SQ | Question | Discipline | Load-bearing because |
|----|----------|------------|----------------------|
| SQ1 | Exact semantics of the current solver (method, error control, tolerances, events) | Julia / DifferentialEquations.jl | wrong semantics -> silently different trajectories |
| SQ2 | no_std Rust design: memory, fixed capacity, error handling, numerics crates | Rust | it is the deliverable |
| SQ3 | Does the port preserve stability and the 1e-8 error bound? How to test equivalence? | Numerical analysis | the acceptance criterion |
| SQ4 | Worst-case step time on the target MCU within a 1 ms budget | Performance | hard real-time constraint |
| SQ5 | Is a straight port even the right move? | Challenger | alternatives may dominate |

## 3. Roster at a glance

| Discipline | Agent | Default model / effort |
|------------|-------|------------------------|
| Algorithms, complexity, distributed systems, PL, formal methods | `computer-science-expert` | opus / xhigh |
| Proofs, probability, optimisation, numerical analysis | `mathematics-expert` | opus / max |
| Physics, simulation numerics, dimensional analysis | `physics-expert` | opus / xhigh |
| Quantum algorithms, error correction, resource estimates | `quantum-computing-expert` | opus / xhigh |
| Rendering, GPU, geometry | `computer-graphics-expert` | opus / high |
| Visual design, typography, colour | `graphic-design-expert` | opus / high |
| Language craft | `rust-expert`, `cpp-expert`, `haskell-expert` (opus / high); `go-expert`, `julia-expert`, `java-expert`, `kotlin-expert`, `python-expert`, `typescript-expert` (sonnet / high) | as listed |
| Containers and deployment | `container-expert` (sonnet / high) | images, Podman/Quadlet, Kubernetes manifests, Helm, Kustomize, RBAC and NetworkPolicy |
| System architecture and trade-offs | `architect` | opus / xhigh |
| Security | `security-auditor` | opus / high |
| Performance engineering | `code-optimizer` | opus / high |
| Constraint analysis, invention | `first-principles-decomposer` | opus / xhigh |
| Cross-domain transfer | `analogy-mapper` | opus / high |
| State of the art, evidence | `paper-researcher`, `deep-researcher` | opus / high |

Defaults are learned frontmatter values; read the agent file when precision matters.

## 4. Size and roles

**Size.** Members = load-bearing disciplines (lead plus specialists, at most 5) + 1 challenger when
stakes are medium or high + 1 diversity-pair member when the crux sits in one discipline (section 5).
Total 2-7. The integrator runs afterwards and is not part of the wave.

Marginal member test: add member k only if `P(discipline k changes the answer) x cost_of_wrong` is
larger than its call plus the extra synthesis reading (the integrator reads every member's output, so
each member adds roughly 10-20% to synthesis cost). Past 5 members integration quality drops; 7 is a
hard cap. Too many disciplines means the problem should be split into two ensembles or a pipeline.

| Role | Count | Job | Typical agent |
|------|-------|-----|---------------|
| Lead | exactly 1 | owns the central SQ; produces the skeleton others plug into; declares the shared assumptions it relies on | the most central domain expert, an ADVANCED-tier expert |
| Specialist | 1-4 (+1 diversity pair) | answers one scoped SQ; states constraints it imposes on others | domain experts, `security-auditor`, `code-optimizer` |
| Challenger | 0-1 | attacks the framing and the likely consensus; proposes alternatives and failure modes | `first-principles-decomposer`, a second expert from a different tier, `analogy-mapper` |
| Integrator | 1, after the wave | merges with provenance and an explicit conflict matrix | `cross-domain-synthesizer`; you yourself for 2-3 members with few conflicts; `mediator` for competing answers |

Challenger timing: concurrent (attacks the problem framing) is cheap; a second-wave challenger
(attacks the members' outputs) catches more but adds one serial step. For high stakes prefer
3-lens `adversarial-verifier` on the integrated answer over a second-wave challenger.

## 5. Diversity plan

Different disciplines already decorrelate errors. Add deliberate diversity only where it pays:

| Situation | Diversity lever |
|-----------|-----------------|
| The crux sits in one discipline | Two members in that discipline from different tiers (e.g. `go-expert` MEDIUM vs `computer-science-expert` ADVANCED) AND different framing ("optimise for correctness" vs "optimise for simplicity") |
| Lead's answer anchors everyone | Run specialists concurrently with the lead, not after it, unless they truly depend on it |
| Members share the same inputs and model | Treat them as one vote when weighing agreement |
| Cost pressure | Give narrow mechanical SQs to MEDIUM/LOW-tier agents (`code-quality-analyst`, `web-searcher`, `file-summarizer`); keep lead and challenger ADVANCED |
| Hard proofs or novel numerics | route that SQ to `mathematics-expert` (max) or `computer-science-expert`/`physics-expert` (xhigh) |

No per-call overrides: the pre-agent hook strips `model`/`effort` from Agent calls (tiers in
`config/models.json` are authoritative). Get diversity by choosing agents of different tiers and by
framing; record each choice and its reason in the roster table.

## 6. The manifest: ENSEMBLE.md

Write `.stack/out/ensemble-assembler/<YYYYMMDD-HHMM>-<slug>-ensemble.md` before launching anyone.

```markdown
# Ensemble: <slug>
## Problem            outcome + acceptance criteria (checkable)
## Sub-questions      | id | question | discipline | owner | depends on | load-bearing because |
## Roster             | agent | role | model / effort (tier default) | why chosen | why not the obvious alternative |
## Glossary           | term | definition | units | notes |
## Shared assumptions A1..An, numbered; members must accept or reject each one they rely on
## Answer interface   (below)
## Handoff plan       integrator, conflict policy, verification step
```

Answer interface every member returns inside Result (it makes integration mechanical; the
`expert-synthesis` skill consumes exactly these fields):

```
ANSWER to <SQ ids>
Position: <1-3 sentences>
Claims: C1..Cn, each with evidence (path:line, command output, citation) and confidence 0..1
Assumptions: A-ids accepted / rejected (with reason); new assumptions introduced
Constraints imposed on others: "<SQ id> must provide/respect <X>" (units)
Risks in my domain: failure modes with likelihood and impact
Would change my answer: <specific evidence or result>
```

## 7. Member brief template

```
ENSEMBLE: <path to ENSEMBLE.md>. Read Problem, Glossary, Shared assumptions, Answer interface.
ROLE: lead | specialist | challenger
YOUR SUB-QUESTION(S): SQ3: <text>
OUT OF SCOPE: SQ1 (julia-expert), SQ2 (rust-expert), SQ4 (code-optimizer). If you need something from
  them, write it under "Constraints imposed on others" instead of answering it.
INPUTS: <paths with line ranges, URLs>
CONSTRAINTS: <tools, turn budget, files not to touch>
ACCEPTANCE: <what a complete answer to your SQ contains>
OUTPUT: Answer interface inside Result; full reasoning in a file under your out_dir.
DOUBTS: per doubt-escalation. Reject a shared assumption explicitly rather than silently working around it.
```

Challenger variant: replace YOUR SUB-QUESTION with "Assume the obvious approach (<one line>) fails
the acceptance criteria. Why would it fail, and which 2-3 alternative approaches would meet them?
Rank alternatives by expected value; give the test that would discriminate between them."

## 8. Execution

| Dependency structure | Execution |
|----------------------|-----------|
| SQs independent, or dependencies expressible as interface constraints | One wave: all members in ONE message, each Agent call with `run_in_background: false`; wave 2 (if any) starts only after every wave 1 result is in |
| 2 or more specialists need the lead's skeleton (e.g. lead picks the architecture) | Wave 1: lead + independent members; wave 2: dependent members + challenger, given wave 1 output paths |
| One member's output gates whether the rest is worth doing | Wave 1: that member only (a feasibility gate) |

Budget and depth: members + integrator + retries must fit `H/2` (`delegation-protocol`). The
assembler should have `remaining_depth >= 2` so members keep at least 1 level to escalate doubts.
At `remaining_depth` 1 members cannot escalate: say so in their briefs and lower confidence.
Header `budget="soft"`: no members, challengers or waves beyond the plan and no retries for
non-load-bearing SQs; `budget="hard"`: assemble nobody (only `file-summarizer`, `quality-control`,
`validator`, `source-summarizer` may be spawned) and return the SQ map with the gaps as Open doubts.

After returns, check per member: every owned SQ answered; interface fields present; assumptions
accepted or rejected; Status and Confidence. Failure or missing fields: one retry with a sharper brief,
or swap to the adjacent agent (`cpp-expert` -> `code-optimizer` for a pure performance SQ). A second
failure becomes an Open doubt on that SQ.

## 9. Handoff

| Member outputs are | Hand to |
|--------------------|---------|
| Complementary pieces, 2-3 members, few conflicts | Integrate yourself with `expert-synthesis` (provenance table, conflict matrix) |
| Complementary pieces, 4+ members or substantial conflicts | `cross-domain-synthesizer` |
| Competing answers to the same SQ | `mediator` on that SQ only (needs remaining_depth >= 3; `/mediate` is main-thread only, so recommend `Workflow name=mediate args={...}` as an Open doubt if the full workflow is wanted), then integrate |
| Divergent numeric estimates | `expert-panel-chair` with the `delphi-method` skill for that estimate (or return `Workflow name=expert-panel args={question, estimate: true}` as an Open doubt) |
| A binary choice with trade-offs surfaced by members | `debate-moderator` |
| A few factual disagreements | `fact-checker` (external facts) or `tester` (runtime behaviour), then integrate |

Integrator brief: ENSEMBLE.md path, member output paths with anchors, the conflicts you noticed,
original acceptance criteria, and the authority table (which member wins on which SQ and why).
High stakes: send the integrated answer to 3-lens `adversarial-verifier` before returning.

## 10. Worked example (continued from section 2)

| Agent | Role | Model / effort | Why chosen | Why not the alternative |
|-------|------|----------------|------------|-------------------------|
| `rust-expert` | lead (SQ2) | opus / high (default) | deliverable is no_std Rust | `cpp-expert`: wrong target language |
| `julia-expert` | specialist (SQ1) | sonnet / high (default) | must read DifferentialEquations.jl semantics exactly | `mathematics-expert` knows methods, not this library's defaults |
| `mathematics-expert` | specialist (SQ3) | opus / max (tier default; per-call overrides are stripped) | equivalence and error-bound argument | `physics-expert`: numerics are generic, not physics-specific |
| `code-optimizer` | specialist (SQ4) | opus / high (default) | worst-case timing on MCU | `rust-expert` already loaded as lead |
| `first-principles-decomposer` | challenger (SQ5) | opus / xhigh (default) | question the port itself (fixed-step with proven bound, codegen, lookup tables) | `analogy-mapper`: less useful when constraints dominate |

One wave (SQ2 states its needs from SQ1/SQ3 as interface constraints). 5 members + integrator +
1 retry reserve = 7 spawns. Returns: julia-expert finds the reference uses `Rodas5P` with adaptive
steps and `abstol=1e-10`; mathematics-expert shows a fixed-step port cannot guarantee 1e-8 on the
stiff transient; code-optimizer estimates 0.31 ms worst case for adaptive Rodas5P on the target class;
the challenger proposes adaptive steps with a step-count cap and a precomputed Jacobian sparsity
pattern. Conflict: rust-expert assumed a cap of 8 rejected attempts per step, rejected by SQ3's
error analysis (A3 rejected). 5 members with a real conflict -> `cross-domain-synthesizer`.

## 11. Checklist before returning

- [ ] Every load-bearing SQ has exactly one owner; disciplines not covered are listed as Open doubts.
- [ ] 2-7 members, one lead; each has a recorded reason and the alternative it beat.
- [ ] ENSEMBLE.md has glossary with units, numbered shared assumptions, and the answer interface.
- [ ] Briefs carry scope and out-of-scope; no pasted blobs.
- [ ] Diversity choices recorded; duplicated disciplines use agents of different tiers and different framings.
- [ ] Handoff choice matches the output type (complements -> synthesis; substitutes -> vote).
- [ ] Result names the roster, the integrated answer (or its path), conflicts and dissent.
