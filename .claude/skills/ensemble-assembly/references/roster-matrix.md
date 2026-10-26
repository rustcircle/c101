# Roster matrix

Model / effort / maxTurns are the initial values from `config/models.json` (`bin/stack agents tiers`);
`maxTurns` and `effort` are re-tuned by the learner (`bin/stack learn apply`), so read
`.claude/agents/<group>/<name>.md` when exact values matter.

## Domain experts

| Agent | Model / effort | maxTurns | MCP | Best for | Not for |
|-------|----------------|----------|-----|----------|---------|
| `computer-science-expert` | opus / xhigh | 450 | - | algorithms and bounds, data structure choice, consistency models, consensus, type systems, compilers, TLA+ style reasoning | language-specific idioms, measured performance |
| `mathematics-expert` | opus / max | 540 | - | proofs, probability and statistics, optimisation, numerical analysis (stability, error bounds, conditioning) | domain modelling assumptions (pair with physics or CS) |
| `physics-expert` | opus / xhigh | 450 | - | physical models, dimensional analysis, limiting cases, simulation integrators and their conservation properties | software design |
| `quantum-computing-expert` | opus / xhigh | 450 | context7 | circuits, algorithms, QEC and decoders, resource estimation, SDK specifics | classical complexity claims beyond BQP context (pair with CS) |
| `computer-graphics-expert` | opus / high | 450 | context7 | rendering, sampling, BRDFs, GPU APIs and shaders, geometry processing, colour pipelines | general GPU compute performance tuning outside graphics (pair with code-optimizer) |
| `graphic-design-expert` | opus / high | 360 | image-gen, image-edit, image-vector | layout, typography, colour, brand, accessible contrast, art direction | image pipeline engineering |
| `rust-expert` | opus / high | 540 | context7 | ownership designs, async, unsafe/FFI audits, no_std, cargo workspaces | algorithmic optimality proofs |
| `cpp-expert` | opus / high | 540 | context7 | modern C++, memory model, UB, sanitizers, SIMD, CMake | Rust or managed runtimes |
| `haskell-expert` | opus / high | 540 | context7 | typed FP design, effects, laziness and space leaks, property testing | low-level systems performance |
| `go-expert` | sonnet / high | 540 | context7 | Go services, concurrency with context, pprof, modules | heavy numerics |
| `julia-expert` | sonnet / high | 540 | context7 | scientific Julia, DifferentialEquations.jl, JuMP, type stability, CUDA.jl | production service architecture |
| `java-expert` | sonnet / high | 540 | context7 | modern Java, virtual threads, JVM GC and JFR, JMH | Kotlin coroutine semantics |
| `kotlin-expert` | sonnet / high | 540 | context7 | coroutines and Flow, structured concurrency, Multiplatform, Compose | JVM GC tuning |
| `python-expert` | sonnet / high | 540 | context7 | typed Python (mypy/pyright), asyncio with TaskGroup, uv packaging, pytest, FastAPI and pydantic v2, profiling | numeric kernels needing native code |
| `typescript-expert` | sonnet / high | 540 | context7 | strict TypeScript, ESM/CJS and package exports, Node services, Vitest/Jest, React components | browser rendering performance, GPU |

## Cross-cutting members

| Agent | Model / effort | maxTurns | Use as | Notes |
|-------|----------------|----------|--------|-------|
| `architect` | opus / xhigh | 360 | lead for system-level designs; specialist for component boundaries | explores 2-4 candidate designs; expensive, so give it the central SQ or none |
| `security-auditor` | opus / high | 360 | specialist on trust boundaries, authn/authz, injection, secrets, supply chain | its sustained objections should be blocking by default in the authority table |
| `code-optimizer` | opus / high | 450 | specialist on measured performance budgets | demands benchmarks; good antidote to speculative performance claims |
| `first-principles-decomposer` | opus / xhigh | 270 | challenger | separates hard constraints from conventions; proposes non-obvious alternatives |
| `analogy-mapper` | opus / high | 270 | challenger or specialist for "has another field solved this?" | cites the source domain's canonical method |
| `paper-researcher` | opus / high | 360 | specialist on state of the art and prior results | jina + exa; reads papers, builds comparison tables |
| `deep-researcher` | opus / high | 720 | evidence gatherer before the ensemble, not usually a member | a coordinator; needs depth below it |
| `tester` | sonnet / high | 450 | empirical arbiter for runtime questions during or after the wave | not a member by default |

## Integrators and deciders (after the wave)

| Agent | Model / effort | Use when |
|-------|----------------|----------|
| `cross-domain-synthesizer` | opus / xhigh | complementary outputs from 4+ members, or real conflicts to resolve with provenance |
| `mediator` | opus / xhigh | members produced competing answers to the same SQ |
| `expert-panel-chair` | opus / high | numeric estimates diverge; run Delphi rounds |
| `debate-moderator` | opus / high | a binary decision with trade-offs remains |
| `adversarial-verifier` | opus / high | verify the integrated answer's load-bearing claims (3 lenses for high stakes) |

## Typical pairings

| Problem shape | Lead | Specialists | Challenger |
|---------------|------|-------------|------------|
| Numerical software port or rewrite | target-language expert | source-language expert, `mathematics-expert`, `code-optimizer` | `first-principles-decomposer` |
| Distributed protocol or storage design | `architect` | `computer-science-expert`, `security-auditor`, language expert | `analogy-mapper` |
| Physically based rendering feature | `computer-graphics-expert` | `physics-expert`, `mathematics-expert`, `cpp-expert` | `first-principles-decomposer` |
| Quantum algorithm feasibility | `quantum-computing-expert` | `computer-science-expert`, `physics-expert`, `paper-researcher` | `mathematics-expert` on a different framing |
| Scientific simulation pipeline | `physics-expert` | `julia-expert` or `cpp-expert`, `mathematics-expert`, `code-optimizer` | `analogy-mapper` |
| Visual identity with generated assets | `graphic-design-expert` | `computer-graphics-expert` (colour pipeline), `paper-researcher` (if research-heavy) | none, use a judge panel on candidate designs instead |
| Polyglot service boundary (JVM + native) | `architect` | `java-expert` or `kotlin-expert`, `rust-expert` or `cpp-expert`, `security-auditor` | `computer-science-expert` |

## Authority overlaps and default tie-breaks

Write these into the Authority section of ENSEMBLE.md so the integrator does not have to guess.

| Overlap | Default authority | Reason |
|---------|-------------------|--------|
| Numerical stability: `mathematics-expert` vs `physics-expert` | mathematics on error bounds and conditioning; physics on which quantities must be conserved | different questions that look like one |
| Algorithmic complexity vs measured speed: `computer-science-expert` vs `code-optimizer` | measurement wins for the given workload; complexity wins for scaling claims beyond measured sizes | evidence type decides |
| Security vs performance | `security-auditor` blocks; `code-optimizer` proposes a compliant alternative | asymmetric cost of error |
| Architecture vs language expert | `architect` on boundaries and data flow; language expert on whether the design is implementable idiomatically | each has veto in their area |
| Two experts in the same discipline (diversity pair) | no default authority; disagreement goes to `mediator` or `adversarial-verifier` | that is why you paired them |
