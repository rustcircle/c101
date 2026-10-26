# Ensemble example: Julia stiff ODE solver to no_std Rust

A complete manifest and the briefs the assembler sent. Paths and numbers are illustrative; the
structure is what to copy.

## ENSEMBLE.md

```markdown
# Ensemble: ode-port-rust

## Problem
Port the plant model solver in sim/PlantModel.jl (solve call at sim/PlantModel.jl:212-240) to a
no_std Rust crate firmware/plant-solver for a Cortex-M7 at 600 MHz with FPU (double precision).
Acceptance:
- trajectories within 1e-8 relative error (per state, max over the 12 reference scenarios in
  sim/scenarios/) of the Julia reference
- worst-case solve step under 1 ms (1 kHz control loop), measured on the target or a cycle-accurate model
- no heap allocation after init; no panics reachable from the public API

## Sub-questions
| id | question | discipline | owner | depends on | load-bearing because |
|----|----------|------------|-------|------------|----------------------|
| SQ1 | Exact solver semantics: algorithm, step control, tolerances, Jacobian handling, events, defaults implied by the call | Julia / SciML | julia-expert | - | wrong semantics silently changes trajectories |
| SQ2 | no_std crate design: state layout, fixed capacities, linear solve, error model, API | Rust | rust-expert (lead) | SQ1, SQ3 via interface | it is the deliverable |
| SQ3 | Can the port meet 1e-8 relative? Error-bound argument and the equivalence test design | numerical analysis | mathematics-expert | SQ1 | the acceptance criterion |
| SQ4 | Worst-case step time and how to measure it on target | performance | code-optimizer | SQ2 via interface | hard real-time limit |
| SQ5 | Is a straight port the right approach at all? | challenger | first-principles-decomposer | - | alternatives may dominate |

## Roster
| agent | role | model / effort | why chosen | why not the obvious alternative |
|-------|------|----------------|------------|---------------------------------|
| rust-expert | lead | opus / high | no_std, fixed capacity, error handling are the core of the deliverable | cpp-expert: wrong language |
| julia-expert | specialist | sonnet / high | must read DifferentialEquations.jl call semantics and defaults precisely | mathematics-expert: knows methods, not library defaults |
| mathematics-expert | specialist | opus / max | stiffness, error control, equivalence argument; not a formal proof | physics-expert: numerics here are generic |
| code-optimizer | specialist | opus / high | worst-case timing methodology on an MCU | rust-expert is already the lead |
| first-principles-decomposer | challenger | opus / xhigh | question the port (codegen, fixed-step with bound, tables) | analogy-mapper: constraints dominate, not analogies |

## Glossary
| term | definition | units | notes |
|------|------------|-------|-------|
| step | one accepted integrator step including rejected attempts before it | - | timing counts rejected attempts |
| relative error | abs(x_rust - x_jl) / max(abs(x_jl), 1e-12) per state component | dimensionless | max over time grid and scenarios |
| worst-case step time | max over all steps in all scenarios of wall time per step | microseconds | measured with DWT cycle counter at 600 MHz |
| reference | Julia output at sim/out/reference/*.csv, Float64 | - | regenerated with the pinned Manifest.toml |

## Shared assumptions
- A1: Float64 on target (FPv5 double-precision FPU present).
- A2: The 12 scenarios cover the operating envelope; no new scenarios in scope.
- A3: A cap of 8 rejected attempts per accepted step (it bounds the worst-case step time) is acceptable.
- A4: Events (callbacks) in the Julia model are limited to the two ContinuousCallbacks at PlantModel.jl:180-205.

## Answer interface
ANSWER to <SQ ids>
Position / Claims (evidence + confidence) / Assumptions accepted or rejected / Constraints imposed on
others / Risks in my domain / Would change my answer

## Handoff plan
Integrator: cross-domain-synthesizer (5 members). Authority: SQ3 wins on accuracy questions,
code-optimizer measurements win on timing, rust-expert on implementability. Verification:
adversarial-verifier (correctness + reproducibility lenses) on the equivalence test design.
```

## Lead brief (rust-expert)

```
ENSEMBLE: .stack/out/ensemble-assembler/20261019-1530-ode-port-rust-ensemble.md
  Read Problem, Glossary, Shared assumptions, Answer interface.
ROLE: lead
YOUR SUB-QUESTION: SQ2. Design the no_std crate firmware/plant-solver: state layout, fixed capacities,
  linear solver for the 12x12 Jacobian, error model, public API, init-time allocation only.
OUT OF SCOPE: SQ1 solver semantics (julia-expert), SQ3 accuracy argument (mathematics-expert),
  SQ4 timing (code-optimizer). State what you need from them under "Constraints imposed on others".
INPUTS: sim/PlantModel.jl:1-260, firmware/Cargo.toml, firmware/memory.x
CONSTRAINTS: no code changes outside .stack/out/rust-expert/; design only; at most ~135 tool calls.
ACCEPTANCE: API sketch with types; capacity table with bytes; no-panic strategy; how SQ1 semantics map
  to the design; explicit list of assumptions accepted/rejected.
OUTPUT: Answer interface in Result; design document under your out_dir.
DOUBTS: per doubt-escalation; reject A3 explicitly if the rejection cap must be higher.
```

## Challenger brief (first-principles-decomposer)

```
ENSEMBLE: <same path>. Read Problem, Glossary, Shared assumptions.
ROLE: challenger
TASK: Assume a straight port of the Julia solver to Rust fails either the 1e-8 accuracy or the 1 ms
  worst-case step. Why would it fail? Propose 2-3 alternative approaches (e.g. code generation from the
  model, fixed-step with a proven error bound, precomputed Jacobian structure, reduced-order model)
  that would meet the acceptance criteria. Rank them by expected value and give, for each, the cheapest
  test that would discriminate it from the straight port.
OUT OF SCOPE: detailed crate design.
OUTPUT: Answer interface in Result; analysis under your out_dir.
```

## Integrator brief (cross-domain-synthesizer)

```
GOAL: one integrated port plan that meets ENSEMBLE.md acceptance criteria, with provenance per claim.
INPUTS: ENSEMBLE.md (path above); member outputs:
  .stack/out/rust-expert/20261019-1541-plant-solver-design.md (L1-L210)
  .stack/out/julia-expert/20261019-1538-solver-semantics.md
  .stack/out/mathematics-expert/20261019-1549-error-analysis.md
  .stack/out/code-optimizer/20261019-1546-timing-method.md
  .stack/out/first-principles-decomposer/20261019-1544-alternatives.md
CONFLICTS NOTICED: (1) A3 rejected by mathematics-expert: under the stiff transient the step controller
  needs up to 12 rejected attempts at the reference tolerances; rust-expert assumed a cap of 8. (2) challenger ranks "adaptive with step cap" above the
  straight port; lead did not consider a cap.
AUTHORITY: as in ENSEMBLE.md Handoff plan.
OUTPUT: integrated plan with claim-level provenance table and conflict resolution matrix; file under
  your out_dir; Result = decision summary + unresolved items.
```

## What came back (summary)

| SQ | Owner | Position | Confidence | Conflicts |
|----|-------|----------|------------|-----------|
| SQ1 | julia-expert | Rodas5P, adaptive, abstol 1e-10, reltol 1e-8, autodiff Jacobian, two continuous callbacks | 0.9 | none |
| SQ2 | rust-expert | fixed-capacity Rosenbrock stepper, LU with partial pivoting on a stack 12x12, Result-based API | 0.75 | assumed A3 |
| SQ3 | mathematics-expert | 1e-8 achievable only with matching step control; fixed-step cannot bound error on the transient | 0.8 | rejects A3 |
| SQ4 | code-optimizer | about 24 us per attempt (12x12 LU + 8 stages) from cycle counts; 0.31 ms worst case at 13 attempts; measure with DWT | 0.7 | needs final design |
| SQ5 | challenger | adaptive with step-count cap + precomputed sparsity pattern; codegen second | 0.7 | complements SQ2 |

Integration outcome: adaptive Rosenbrock port with a step-count cap, analytic Jacobian generated from
the model (removes autodiff mismatch), rejection cap raised to 12 (A3 revised), equivalence test over the 12
scenarios with per-state relative error; open doubt on event localisation accuracy near callbacks.
