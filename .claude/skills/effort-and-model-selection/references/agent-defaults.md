# Agent tiers and alternatives

Tier, initial effort and maxTurns per agent from `config/models.json` (rendered by
`bin/stack agents tiers --apply`). Effort, maxTurns and autoCompactWindow then move under the learner
within the bounds from `config/learning.json` (default bounds: maxTurns 5-1000, effort low-max).
Live values: `bin/stack agents list`. Per-call model/effort is stripped by the pre-agent hook; choose
the cheaper or stronger agent instead. Tiers: ADVANCED = ADVANCED_MODEL (claude-opus-5-5), MEDIUM =
MEDIUM_MODEL (claude-sonnet-5-5), LOW = LOW_MODEL (claude-haiku-5-5).

Reading the table: "cheaper" and "stronger" name the agent to pick when a job is clearly easier or
harder than this agent's typical work. A typical job goes to the agent itself. `-` means no useful
alternative; fix the brief or split the job instead. Re-tiering is stack-tuner's call
(`bin/stack agents set NAME tier=<TIER>`, then `bin/stack agents tiers --apply`).

## Orchestration

| Agent | Tier | Effort | maxTurns | Bounds (turns / effort) | Cheaper agent | Stronger agent |
|---|---|---|---|---|---|---|
| delegator | ADVANCED | high | 900 | 900-3000 / medium-max | - (main thread) | - (main thread) |
| orchestrator | ADVANCED | high | 900 | 900-3000 / medium-max | concurrent-dispatcher (LOW) for a flat fan-out | split the project; main thread only: Workflow name=plan-tournament |
| swarm-coordinator | ADVANCED | medium | 660 | 660-3000 | concurrent-dispatcher (LOW) when shards need no merge judgement | orchestrator (ADVANCED) for dependent, heterogeneous work |
| mesh-router | MEDIUM | high | 660 | 660-3000 | concurrent-dispatcher (LOW) | ensemble-assembler (ADVANCED) |
| ensemble-assembler | ADVANCED | high | 540 | 540-3000 | mesh-router (MEDIUM) | expert-panel-chair (ADVANCED) or mediator (ADVANCED) |
| concurrent-dispatcher | LOW | medium | 450 | 450-3000 | - (floor; or parallel Agent calls yourself) | swarm-coordinator (ADVANCED) when dedup or coverage matters |
| mediator | ADVANCED | xhigh | 540 | 540-1800 / high-max | one domain expert for a binary choice | expert-panel-chair (ADVANCED) for calibrated estimates |

## Planning

| Agent | Tier | Effort | maxTurns | Bounds (turns / effort) | Cheaper agent | Stronger agent |
|---|---|---|---|---|---|---|
| planner | ADVANCED | high | 240 | 240-3000 | - (plan 5 or fewer obvious nodes yourself) | architect (ADVANCED) for system-level goals |
| architect | ADVANCED | xhigh | 360 | 360-3000 / high-max | planner (ADVANCED) | mediator (ADVANCED) over two architect designs |
| plan-critic | ADVANCED | high | 180 | 180-3000 | validator (MEDIUM) for mechanical checks | adversarial-verifier (ADVANCED) |

## Quality

| Agent | Tier | Effort | maxTurns | Bounds (turns / effort) | Cheaper agent | Stronger agent |
|---|---|---|---|---|---|---|
| reviewer | ADVANCED | high | 360 | 360-3000 | code-quality-analyst (MEDIUM) for structure only | security-auditor (ADVANCED), then adversarial-verifier (ADVANCED) |
| adversarial-verifier | ADVANCED | high | 270 | 48-3000 | fact-checker (MEDIUM) or tester (MEDIUM) | mathematics-expert (ADVANCED) or security-auditor (ADVANCED) |
| validator | MEDIUM | medium | 270 | 270-3000 | file-summarizer (LOW) to read logs | quality-control (ADVANCED) |
| tester | MEDIUM | high | 450 | 450-3000 | validator (MEDIUM) to run existing tests | debugger (ADVANCED) |
| quality-control | ADVANCED | medium | 210 | 210-3000 | validator (MEDIUM) | adversarial-verifier (ADVANCED) on the riskiest claim |
| code-quality-analyst | MEDIUM | medium | 270 | 270-3000 | file-summarizer (LOW) for metric extraction | reviewer (ADVANCED) or architect (ADVANCED) |
| code-optimizer | ADVANCED | high | 450 | 450-3000 | go/java/kotlin/julia-expert (MEDIUM) | computer-science-expert (ADVANCED) |
| security-auditor | ADVANCED | high | 360 | 360-3000 | code-quality-analyst (MEDIUM) for advisory triage | plus adversarial-verifier (ADVANCED) per finding |
| debugger | ADVANCED | high | 480 | 480-3000 | tester (MEDIUM) to reproduce | the domain expert, e.g. cpp-expert (ADVANCED) |

## Research

| Agent | Tier | Effort | maxTurns | Bounds (turns / effort) | Cheaper agent | Stronger agent |
|---|---|---|---|---|---|---|
| quick-researcher | MEDIUM | low | 120 | 60-600 / low-medium | web-scraper (LOW) for a known URL | deep-researcher (ADVANCED) |
| deep-researcher | ADVANCED | high | 720 | 120-2400 | quick-researcher (MEDIUM) | main thread only: Workflow name=research-sweep |
| web-searcher | MEDIUM | low | 150 | 60-3000 | web-scraper (LOW) for known URLs | quick-researcher (MEDIUM) |
| web-scraper | LOW | low | 240 | 240-3000 | - (floor) | browser-operator (MEDIUM) for JS-heavy pages |
| web-crawler | LOW | medium | 360 | 360-3000 | web-scraper (LOW) for single pages | browser-operator (MEDIUM) |
| browser-operator | MEDIUM | medium | 450 | 450-3000 | web-scraper (LOW) for static pages | - (split the flow) |
| computer-operator | MEDIUM | medium | 450 | 450-3000 | browser-operator (MEDIUM) for web apps | - (interactive only; SDK: peekaboo or blocked) |
| paper-researcher | ADVANCED | high | 360 | 216-3000 | source-summarizer (LOW) per known paper | deep-researcher (ADVANCED) |
| fact-checker | MEDIUM | medium | 180 | 36-3000 | quick-researcher (MEDIUM) for one lookup | adversarial-verifier (ADVANCED) |
| source-summarizer | LOW | low | 105 | 105-600 / low-medium | - (floor) | paper-researcher (ADVANCED) for dense papers |
| file-summarizer | LOW | low | 120 | 120-600 / low-medium | - (floor) | the domain expert when code judgement is needed |

## Experts

| Agent | Tier | Effort | maxTurns | Bounds (turns / effort) | Cheaper agent | Stronger agent |
|---|---|---|---|---|---|---|
| computer-graphics-expert | ADVANCED | high | 450 | 450-3000 | quick-researcher (MEDIUM) for API lookups | mathematics-expert (ADVANCED) for sampling maths |
| computer-science-expert | ADVANCED | xhigh | 450 | 450-3000 | go/java/kotlin/python/typescript-expert (MEDIUM) to implement | mathematics-expert (ADVANCED) |
| quantum-computing-expert | ADVANCED | xhigh | 450 | 450-3000 | quick-researcher (MEDIUM) for SDK lookups | physics-expert (ADVANCED) or mathematics-expert (ADVANCED) |
| rust-expert | ADVANCED | high | 540 | 540-3000 | code-quality-analyst (MEDIUM) for lint triage | computer-science-expert (ADVANCED) |
| cpp-expert | ADVANCED | high | 540 | 540-3000 | code-quality-analyst (MEDIUM) for lint triage | computer-science-expert (ADVANCED) for memory-model questions |
| go-expert | MEDIUM | high | 540 | 540-3000 | - | computer-science-expert (ADVANCED) or rust-expert (ADVANCED) |
| haskell-expert | ADVANCED | high | 540 | 540-3000 | - | computer-science-expert (ADVANCED) for type-level theory |
| julia-expert | MEDIUM | high | 540 | 540-3000 | - | computer-science-expert (ADVANCED) or physics-expert (ADVANCED) |
| java-expert | MEDIUM | high | 540 | 540-3000 | - | computer-science-expert (ADVANCED) |
| kotlin-expert | MEDIUM | high | 540 | 540-3000 | - | computer-science-expert (ADVANCED) |
| python-expert | MEDIUM | high | 540 | 540-3000 | - | computer-science-expert (ADVANCED) |
| typescript-expert | MEDIUM | high | 540 | 540-3000 | - | computer-science-expert (ADVANCED) |
| mathematics-expert | ADVANCED | max | 540 | 540-1800 / high-max | tester (MEDIUM) for a numeric sanity script | adversarial-verifier (ADVANCED) per proof step |
| physics-expert | ADVANCED | xhigh | 450 | 450-3000 | quick-researcher (MEDIUM) for constants and units | mathematics-expert (ADVANCED) |
| graphic-design-expert | ADVANCED | high | 360 | 360-3000 | image-generator (MEDIUM) to produce assets | - |

## Image

| Agent | Tier | Effort | maxTurns | Bounds (turns / effort) | Cheaper agent | Stronger agent |
|---|---|---|---|---|---|---|
| image-generator | MEDIUM | medium | 270 | 270-3000 | - | graphic-design-expert (ADVANCED) reviews |
| image-editor | MEDIUM | medium | 270 | 270-3000 | - | graphic-design-expert (ADVANCED) reviews |
| vector-artist | MEDIUM | medium | 270 | 270-3000 | - | graphic-design-expert (ADVANCED) reviews |

## Synthesis

| Agent | Tier | Effort | maxTurns | Bounds (turns / effort) | Cheaper agent | Stronger agent |
|---|---|---|---|---|---|---|
| cross-domain-synthesizer | ADVANCED | xhigh | 360 | 360-3000 / high-max | merge 2 compatible reports yourself | expert-panel-chair (ADVANCED) |
| expert-panel-chair | ADVANCED | high | 540 | 540-3000 | one domain expert | mediator (ADVANCED) to pick among candidates |
| debate-moderator | ADVANCED | high | 360 | 360-3000 | adversarial-verifier (ADVANCED) on one claim | expert-panel-chair (ADVANCED) |
| analogy-mapper | ADVANCED | high | 270 | 270-3000 | quick-researcher (MEDIUM) for a known analogy | cross-domain-synthesizer (ADVANCED) |
| first-principles-decomposer | ADVANCED | xhigh | 270 | 270-3000 | planner (ADVANCED) | mathematics-expert (ADVANCED) |
| general-chat | MEDIUM | low | 105 | 105-600 / low-high | - (floor) | quick-researcher (MEDIUM) when sources are needed |

## Meta

| Agent | Tier | Effort | maxTurns | Bounds (turns / effort) | Cheaper agent | Stronger agent |
|---|---|---|---|---|---|---|
| stack-tuner | MEDIUM | medium | 180 | 180-3000 | - | agent-architect (ADVANCED) |
| agent-architect | ADVANCED | high | 360 | 360-3000 | stack-tuner (MEDIUM) for frontmatter edits | - |

## Built-in agents

`general-purpose`, `Explore` and `Plan` are Claude Code built-ins with no stack frontmatter; the
learner observes them but has no file to tune. Do not pass `model`/`effort` on Agent calls (stripped).
Prefer a stack agent of the right tier. Only a saved workflow run by the main thread may pass `model`
for agentType general-purpose, as alias opus, sonnet or haiku.
