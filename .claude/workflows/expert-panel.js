export const meta = {
  name: 'expert-panel',
  description: 'Delphi expert panel: anonymous independent answers, feedback computed in code (median/IQR, log-odds pool, Borda, clustered arguments, fact-checked cruxes), revision rounds until convergence or stable dissent, then expert-panel-chair synthesis of consensus and minority views.',
  whenToUse: 'A judgment question where a calibrated group view with explicit dissent beats one expert: effort or size estimates (P10/P50/P90), event probabilities, a ranked choice among named options, or an open assessment. args {question, experts?: [agentType | {agentType, perspective?, model?: "opus"|"sonnet"|"haiku" (general-purpose only)}], rounds?: 3 (max 4), estimate?: boolean, kind?: "quantity"|"probability"|"choice"|"open", unit?, options?: [string], evidence?: [path], checkCruxes?: true, maxCruxChecks?: 3, iqrThreshold?, frame?: true, force?: false, runTag?}. Use mediate instead when the job is picking one solution among generated candidates.',
  phases: [
    { title: 'Frame', detail: 'expert-panel-chair makes the question resolvable (units, horizon, resolution, options) and selects 4-7 diverse panelists when none are given' },
    { title: 'Round 1', detail: 'every panelist answers blind and independently under an anonymous label P1..Pn' },
    { title: 'Feedback', detail: 'statistics in code (median, IQR, relative IQR, per-level median and Vincentized mean quantiles, log-odds pool, plurality and Borda); source-summarizer clusters arguments; fact-checker settles up to 3 checkable cruxes per round' },
    { title: 'Revise', detail: 'rounds 2..k: each panelist sees its own answer plus the anonymous packet and revises or holds with a new reason; stop on convergence, stability or the round cap' },
    { title: 'Synthesize', detail: 'expert-panel-chair in synthesis mode writes the consensus, convergence table, minority report and herding verdict to .stack/out/expert-panel/<slug>/' },
  ],
}

// ---------------------------------------------------------------------------
// Delphi panel. Statistics, stopping rules, pooling and the herding check are
// computed here, deterministically; agents only answer, cluster, check and write.
// ---------------------------------------------------------------------------

const notes = []
function note(msg) { notes.push(msg); log(msg) }

function parseArgs(raw) {
  let a = raw
  if (typeof a === 'string') {
    try { a = JSON.parse(a) } catch (e) { a = { question: a } }
    if (typeof a === 'string') a = { question: a }
  }
  return a && typeof a === 'object' && !Array.isArray(a) ? a : {}
}
const A = parseArgs(args)
const QUESTION = typeof A.question === 'string' ? A.question.trim() : ''
if (!QUESTION) {
  return {
    started: false,
    reason: 'args.question (non-empty string) is required',
    next: 'Run Workflow expert-panel with args {question: "How many engineer-weeks to migrate service X from Postgres 13 to 17 with zero downtime?", estimate: true, unit: "engineer-weeks", rounds: 3} or {question, kind: "choice", options: ["A: ...", "B: ..."]}',
  }
}

const AGENTS = [
  'delegator', 'orchestrator', 'swarm-coordinator', 'mesh-router', 'ensemble-assembler', 'concurrent-dispatcher', 'mediator',
  'planner', 'architect', 'plan-critic',
  'reviewer', 'adversarial-verifier', 'validator', 'tester', 'quality-control', 'code-quality-analyst', 'code-optimizer', 'security-auditor', 'debugger',
  'quick-researcher', 'deep-researcher', 'web-searcher', 'web-scraper', 'web-crawler', 'browser-operator', 'computer-operator', 'paper-researcher', 'fact-checker', 'source-summarizer', 'file-summarizer',
  'computer-graphics-expert', 'computer-science-expert', 'quantum-computing-expert', 'rust-expert', 'cpp-expert', 'go-expert', 'haskell-expert', 'julia-expert', 'java-expert', 'kotlin-expert', 'python-expert', 'typescript-expert', 'mathematics-expert', 'physics-expert', 'graphic-design-expert',
  'image-generator', 'image-editor', 'vector-artist',
  'cross-domain-synthesizer', 'expert-panel-chair', 'debate-moderator', 'analogy-mapper', 'first-principles-decomposer', 'general-chat',
  'stack-tuner', 'agent-architect', 'general-purpose',
]
// Agents that make sense as panelists (judgment from domain knowledge), with the strengths the chair selects on.
const PANEL_ROSTER = {
  'computer-science-expert': 'algorithms, complexity, distributed systems, consensus, PL and type theory',
  'mathematics-expert': 'proofs, probability and statistics, optimisation, numerical analysis',
  'physics-expert': 'physical limits, dimensional analysis, statistical mechanics, computational physics',
  'quantum-computing-expert': 'quantum algorithms, error correction, resource estimates',
  'computer-graphics-expert': 'rendering, GPU programming, geometry, real-time budgets',
  'rust-expert': 'Rust systems, async, unsafe, performance',
  'cpp-expert': 'modern C++, memory model, UB, toolchains',
  'go-expert': 'Go services, concurrency, pprof, gRPC',
  'haskell-expert': 'typed FP, effects, laziness, property testing',
  'julia-expert': 'scientific computing, type stability, SciML',
  'java-expert': 'JVM, virtual threads, GC tuning, Spring/Quarkus',
  'kotlin-expert': 'Kotlin, coroutines, Multiplatform, Android',
  'python-expert': 'Python, typing, asyncio, packaging with uv, pytest, FastAPI',
  'typescript-expert': 'TypeScript, Node, strict types, ESM/CJS, React',
  'graphic-design-expert': 'visual design, typography, brand, accessibility contrast',
  'architect': 'system architecture trade-offs, scalability, failure modes',
  'planner': 'decomposition, schedules, dependency and effort estimation',
  'plan-critic': 'red-teaming plans, hidden dependencies, optimism bias',
  'code-optimizer': 'performance engineering, profiling, cost models',
  'security-auditor': 'threat models, exposure likelihood, defensive security',
  'reviewer': 'code-level correctness and maintainability judgment',
  'code-quality-analyst': 'complexity, coupling, change-risk metrics',
  'debugger': 'failure analysis, root causes, operational incidents',
  'paper-researcher': 'state of the academic literature, credibility of results',
  'deep-researcher': 'evidence across many sources, industry practice',
  'first-principles-decomposer': 'bounds from fundamentals, back-of-envelope estimates',
  'analogy-mapper': 'reference classes and analogous cases from other fields',
  'adversarial-verifier': 'skeptic; argues why a claim or estimate is wrong',
  'general-purpose': 'generalist baseline',
}
const DEFAULT_PANEL = [
  { agentType: 'computer-science-expert', perspective: 'Reason from algorithms, systems and known reference systems.' },
  { agentType: 'mathematics-expert', perspective: 'Reason from base rates and explicit probabilistic models.' },
  { agentType: 'architect', perspective: 'Reason from comparable production systems and their failure modes.' },
  { agentType: 'first-principles-decomposer', perspective: 'Derive bounds from fundamentals before adjusting.' },
  { agentType: 'plan-critic', perspective: 'Assume the optimistic answer is wrong; hunt for what was missed.' },
]
// Tiers are authoritative: only general-purpose takes a model alias (the three tier aliases); never effort.
const MODELS = ['opus', 'sonnet', 'haiku']
const KINDS = ['quantity', 'probability', 'choice', 'open']

function clampInt(v, lo, hi, dflt) {
  const n = Number(v)
  if (!Number.isFinite(n)) return dflt
  return Math.max(lo, Math.min(hi, Math.round(n)))
}
function slugify(s, max) {
  const n = max || 48
  const t = String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  if (t.length <= n) return t || 'panel'
  const cut = t.slice(0, n)
  const at = cut.lastIndexOf('-')
  return (at >= n / 2 ? cut.slice(0, at) : cut).replace(/-+$/g, '') || 'panel'
}
function tokens(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9.%]+/g, ' ').split(' ').map(w => w.replace(/^\.+|\.+$/g, '')).filter(w => w.length > 2 || /\d/.test(w))
}
function jaccard(a, b) {
  const x = new Set(tokens(a)), y = new Set(tokens(b))
  if (!x.size && !y.size) return 1
  let inter = 0
  for (const w of x) if (y.has(w)) inter++
  return inter / (x.size + y.size - inter)
}
function dedupTexts(items, getText, threshold) {
  const kept = []
  for (const it of items) {
    if (!kept.some(k => jaccard(getText(k), getText(it)) >= threshold)) kept.push(it)
  }
  return kept
}
function cleanOpts(o) {
  const r = {}
  for (const k of Object.keys(o)) if (o[k] !== undefined && o[k] !== null && o[k] !== '') r[k] = o[k]
  return r
}
async function call(prompt, opts) {
  try {
    return await agent(prompt, cleanOpts(opts))
  } catch (e) {
    note(`${opts.label}: agent call failed (${String((e && e.message) || e).slice(0, 160)})`)
    return null
  }
}
function lowBudget(min) { return !!(budget && budget.total && budget.remaining() < min) }

// --- statistics (type-7 quantiles, identical to Python statistics.quantiles(method='inclusive')) ---
function quantile(xs, q) {
  const s = xs.filter(Number.isFinite).slice().sort((a, b) => a - b)
  if (!s.length) return null
  const h = (s.length - 1) * q
  const lo = Math.floor(h), hi = Math.ceil(h)
  return s[lo] + (h - lo) * (s[hi] - s[lo])
}
function median(xs) { return quantile(xs, 0.5) }
function mean(xs) { return xs.length ? xs.reduce((t, x) => t + x, 0) / xs.length : null }
function round(x, d) {
  if (x === null || x === undefined || !Number.isFinite(x)) return x
  const f = Math.pow(10, d === undefined ? 4 : d)
  return Math.round(x * f) / f
}
function logit(p) { return Math.log(p / (1 - p)) }
function sigmoid(z) { return 1 / (1 + Math.exp(-z)) }
function clipP(p) { return Math.min(0.99, Math.max(0.01, p)) }

// Quantile function of one panelist from (P10, P50, P90): piecewise linear, tails extrapolated with the
// adjacent segment slope (so u=0 maps to P10 - 0.25*(P50-P10) and u=1 to P90 + 0.25*(P90-P50)).
function panelistQuantile(e, u) {
  if (u <= 0.5) return e.p10 + (u - 0.1) * (e.p50 - e.p10) / 0.4
  return e.p50 + (u - 0.5) * (e.p90 - e.p50) / 0.4
}
// Equal-weight linear opinion pool (mixture) quantiles via K midpoint samples per panelist.
function linearPoolQuantiles(ests) {
  const K = 40, pooled = []
  for (const e of ests) for (let k = 0; k < K; k++) pooled.push(panelistQuantile(e, (k + 0.5) / K))
  return { p10: quantile(pooled, 0.1), p50: quantile(pooled, 0.5), p90: quantile(pooled, 0.9) }
}

// ---------------- configuration ----------------
const ROUNDS = clampInt(A.rounds, 1, 4, 3)
if (A.rounds !== undefined && ROUNDS !== Number(A.rounds)) note(`rounds clamped to ${ROUNDS} (allowed 1-4; later rounds add conformity, not accuracy)`)
const CHECK_CRUXES = A.checkCruxes !== false
const MAX_CRUX_CHECKS = clampInt(A.maxCruxChecks, 0, 6, 3)
const CLUSTER_THRESHOLD = clampInt(A.clusterThreshold, 0, 50, 6)
const SLUG = slugify(QUESTION, 48)
const TAG = typeof A.runTag === 'string' && A.runTag.trim() ? '-' + slugify(A.runTag, 24) : ''
const RUN_DIR = `.stack/out/expert-panel/${SLUG}${TAG}`
const EVIDENCE = Array.isArray(A.evidence) ? A.evidence.filter(x => typeof x === 'string' && x.trim()) : (typeof A.evidence === 'string' ? [A.evidence] : [])
if (!TAG) note(`output directory ${RUN_DIR} (pass runTag to keep separate runs of the same question apart)`)

function normalizePanel(list, source) {
  if (!Array.isArray(list)) return []
  const out = [], perType = {}
  for (const raw of list) {
    const e = typeof raw === 'string' ? { agentType: raw } : (raw && typeof raw === 'object' ? raw : null)
    if (!e || typeof e.agentType !== 'string') { note(`${source}: dropped malformed panelist entry ${JSON.stringify(raw).slice(0, 80)}`); continue }
    const agentType = e.agentType.trim()
    if (!AGENTS.includes(agentType)) { note(`${source}: dropped unknown agent type "${agentType}"`); continue }
    const model = agentType === 'general-purpose' && MODELS.includes(e.model) ? e.model : undefined
    if (e.model && !model) note(`${source}: ignored model "${e.model}" for ${agentType} (tiers are authoritative; only general-purpose takes opus|sonnet|haiku)`)
    if (e.effort) note(`${source}: ignored effort "${e.effort}" for ${agentType} (per-call effort is not allowed)`)
    perType[agentType] = (perType[agentType] || 0) + 1
    if (perType[agentType] > 2) { note(`${source}: dropped third ${agentType} (at most two of one type; diversity of information beats headcount)`); continue }
    out.push({ agentType, model, perspective: typeof e.perspective === 'string' ? e.perspective.trim() : '' })
  }
  if (out.length > 7) {
    note(`${source}: panel capped at 7; dropped ${out.slice(7).map(p => p.agentType).join(', ')}`)
    return out.slice(0, 7)
  }
  return out
}

// ---------------- Frame ----------------
phase('Frame')
const givenPanel = normalizePanel(A.experts, 'args.experts')
const hintKind = KINDS.includes(A.kind) ? A.kind : (Array.isArray(A.options) && A.options.length ? 'choice' : (A.estimate === true ? 'quantity' : ''))
const needFrame = A.frame !== false || givenPanel.length < 3

const FRAME_SCHEMA = {
  type: 'object',
  properties: {
    question: { type: 'string', description: 'the resolvable restatement every panelist receives, self-contained' },
    kind: { type: 'string', enum: KINDS },
    unit: { type: 'string', description: 'unit for quantity questions, e.g. engineer-weeks, ms p99, USD/month' },
    horizon: { type: 'string', description: 'time horizon or resolution date' },
    resolution: { type: 'string', description: 'how the truth would be established' },
    definitions: { type: 'array', items: { type: 'string' } },
    options: { type: 'array', items: { type: 'string' }, description: 'choice only: short stable ids with a label, e.g. "A: managed Kafka"' },
    panel: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          agentType: { type: 'string' },
          model: { type: 'string', description: 'only for general-purpose: opus | sonnet | haiku' },
          perspective: { type: 'string' },
        },
        required: ['agentType', 'perspective'],
      },
    },
    doubt: { type: 'string', description: 'non-empty only if the question cannot be made resolvable without changing what is asked' },
  },
  required: ['question', 'kind', 'resolution', 'panel'],
}

let frame = null
if (needFrame) {
  const rosterLines = Object.keys(PANEL_ROSTER).map(k => `- ${k}: ${PANEL_ROSTER[k]}`).join('\n')
  const panelBlock = givenPanel.length >= 3
    ? `The panel is FIXED by the caller: ${givenPanel.map(p => p.agentType + (p.model ? '/' + p.model : '')).join(', ')}. Return exactly these entries in "panel", in this order, adding a one-line perspective for each that decorrelates them (different reference class, method or failure lens).`
    : `Select 4-7 panelists from this roster. Diversity of information beats headcount: at most two of one agent type, and then with a clearly different perspective (models are fixed by each agent's tier; to vary the model pick agent types from different tiers, e.g. go-expert or java-expert are MEDIUM tier). Include at least one skeptic (plan-critic or adversarial-verifier) for estimates and probabilities. Give every panelist a one-line perspective.\n${rosterLines}`
  frame = await call(
    `You are the expert-panel chair, called by the expert-panel workflow in FRAME mode. Do only framing and panel selection: do not spawn panelists, do not run rounds, do not launch workflows; at most 3 quick lookups if a term needs a definition.

Raw question: ${QUESTION}
Caller hints: kind=${hintKind || 'unspecified'}; unit=${A.unit || 'unspecified'}; options=${Array.isArray(A.options) ? JSON.stringify(A.options) : 'none'}; evidence pack=${EVIDENCE.length ? EVIDENCE.join(', ') : 'none'}

Make the question Delphi-able:
1. One resolvable proposition or quantity, with units, horizon and a definition for every loaded term ("done", "production", "scale", "secure").
2. kind: "quantity" (panelists give P10/P50/P90 in the unit), "probability" (an event with a resolution date), "choice" (named options; panelists rank all of them), or "open" only when none of the others fit. Respect the caller's kind hint unless it makes the question unanswerable.
3. resolution: how and when the truth would be established (measurement, benchmark, date, document).
4. For choice, options are short stable ids plus a label ("A: keep Postgres, add read replicas").
5. If the question cannot be made resolvable without changing what the caller asks, put the reason in "doubt" and your best repaired question in "question".

Panel: ${panelBlock}`,
    { label: 'frame', phase: 'Frame', agentType: 'expert-panel-chair', schema: FRAME_SCHEMA },
  )
  if (!frame) note('frame: chair unavailable; using the raw question and caller hints')
}

if (frame && frame.doubt && frame.doubt.trim() && A.force !== true) {
  return {
    started: false,
    reason: 'the chair judged the question not resolvable as stated',
    doubt: frame.doubt,
    proposed_question: frame.question,
    proposed_kind: frame.kind,
    next: 'Re-run with the proposed question (or a sharper one), or pass force: true to run the panel on the repaired question anyway.',
    notes,
  }
}

const KIND = KINDS.includes(A.kind) ? A.kind : (frame && KINDS.includes(frame.kind) ? frame.kind : (hintKind || 'open'))
const FQ = {
  question: (frame && frame.question) || QUESTION,
  unit: A.unit || (frame && frame.unit) || '',
  horizon: (frame && frame.horizon) || '',
  resolution: (frame && frame.resolution) || '',
  definitions: (frame && Array.isArray(frame.definitions)) ? frame.definitions : [],
  options: Array.isArray(A.options) && A.options.length ? A.options.map(String) : ((frame && Array.isArray(frame.options)) ? frame.options.map(String) : []),
}
if (KIND === 'choice' && FQ.options.length < 2) {
  return { started: false, reason: 'kind "choice" needs at least two options', next: 'Pass options: ["A: ...", "B: ..."] or use kind "open".', frame: FQ, notes }
}
if (KIND === 'quantity' && !FQ.unit) note('quantity question without a unit; panelists are told to state their unit in the answer')

let panel = givenPanel.length >= 3 ? givenPanel.slice() : []
if (panel.length && frame && Array.isArray(frame.panel)) {
  // keep caller's types, adopt the chair's perspective lines when the caller gave none
  panel = panel.map((p, i) => {
    const fp = frame.panel[i]
    return fp && fp.agentType === p.agentType && !p.perspective ? Object.assign({}, p, { perspective: fp.perspective || '' }) : p
  })
}
if (!panel.length) {
  panel = normalizePanel(frame && frame.panel, 'chair selection')
  if (panel.length < 3) {
    note(`chair selection produced ${panel.length} usable panelists; falling back to the default 5-member panel`)
    panel = normalizePanel(DEFAULT_PANEL, 'default panel')
  }
}
if (givenPanel.length > 0 && givenPanel.length < 3) note(`args.experts had ${givenPanel.length} valid entries (minimum 3); the chair selected the panel instead`)
panel = panel.map((p, i) => Object.assign({}, p, { label: 'P' + (i + 1) }))
log(`panel of ${panel.length}: ${panel.map(p => p.label + '=' + p.agentType).join(', ')}; kind=${KIND}; up to ${ROUNDS} rounds`)

// ---------------- answer schema / normalisation ----------------
function answerSchema(revise) {
  const props = {
    answer: { type: 'string', description: 'one paragraph; for choice start with the option id you rank first' },
    key_arguments: { type: 'array', items: { type: 'string' }, maxItems: 3, description: 'at most 3, each <= 2 lines with an evidence pointer (path, URL, standard, or "reasoning")' },
    cruxes: { type: 'array', items: { type: 'string' }, description: 'observations that would move you by >2x or >20 points; prefix "CHECKABLE: " when a lookup could settle it' },
    confidence: { type: 'number', minimum: 0, maximum: 1 },
  }
  const req = ['answer', 'key_arguments', 'confidence']
  if (KIND === 'quantity') {
    props.estimate = {
      type: 'object',
      properties: { p10: { type: 'number' }, p50: { type: 'number' }, p90: { type: 'number' }, unit: { type: 'string' } },
      required: ['p10', 'p50', 'p90'],
    }
    req.push('estimate')
  } else if (KIND === 'probability') {
    props.probability = { type: 'number', minimum: 0, maximum: 1 }
    req.push('probability')
  } else if (KIND === 'choice') {
    props.ranking = { type: 'array', items: { type: 'string' }, description: 'ALL option ids, best first' }
    req.push('ranking')
  }
  if (revise) {
    props.moved = { type: 'boolean', description: 'true if your estimate/probability/ranking/position changed materially since your last round' }
    props.moved_because = { type: 'string', description: 'if moved: the packet argument or evidence ruling that moved you' }
    props.hold_reason = { type: 'string', description: 'if you hold outside the IQR or against the majority: a reason not already in the packet' }
    req.push('moved')
  }
  return { type: 'object', properties: props, required: req }
}

function optionId(s) {
  const t = String(s || '').trim()
  for (const o of FQ.options) {
    const id = o.split(':')[0].trim()
    if (t === o || t === id || t.toLowerCase() === id.toLowerCase() || t.toLowerCase().startsWith(id.toLowerCase() + ':') || t.toLowerCase() === o.toLowerCase()) return id
  }
  return null
}
const OPTION_IDS = FQ.options.map(o => o.split(':')[0].trim())

function normalizeAnswer(a, label) {
  if (!a) return null
  const r = Object.assign({}, a)
  if (KIND === 'quantity') {
    const e = a.estimate || {}
    const xs = [Number(e.p10), Number(e.p50), Number(e.p90)]
    if (!xs.every(Number.isFinite)) { note(`${label}: estimate not numeric; excluded from statistics`); r.estimate = null }
    else {
      const s = xs.slice().sort((x, y) => x - y)
      if (s[0] !== xs[0] || s[2] !== xs[2]) note(`${label}: P10/P50/P90 out of order; sorted`)
      r.estimate = { p10: s[0], p50: s[1], p90: s[2], unit: e.unit || FQ.unit }
    }
  } else if (KIND === 'probability') {
    const p = Number(a.probability)
    r.probability = Number.isFinite(p) ? Math.min(1, Math.max(0, p)) : null
    if (r.probability === null) note(`${label}: probability missing; excluded from statistics`)
  } else if (KIND === 'choice') {
    const seen = new Set(), rk = []
    for (const x of (Array.isArray(a.ranking) ? a.ranking : [])) {
      const id = optionId(x)
      if (id && !seen.has(id)) { seen.add(id); rk.push(id) }
    }
    if (rk.length < OPTION_IDS.length) note(`${label}: ranking covered ${rk.length}/${OPTION_IDS.length} options; unranked options get 0 Borda points`)
    r.ranking = rk
  }
  r.key_arguments = (Array.isArray(a.key_arguments) ? a.key_arguments : []).slice(0, 3)
  r.cruxes = Array.isArray(a.cruxes) ? a.cruxes : []
  return r
}

function valueOf(a) {
  if (!a) return null
  if (KIND === 'quantity') return a.estimate ? a.estimate.p50 : null
  if (KIND === 'probability') return a.probability
  return null
}

function computeStats(answers) {
  const live = answers.filter(Boolean)
  const s = { n: live.length }
  if (KIND === 'quantity' || KIND === 'probability') {
    const vals = live.map(valueOf).filter(v => v !== null && Number.isFinite(v))
    s.n_numeric = vals.length
    s.values_sorted = vals.slice().sort((x, y) => x - y).map(v => round(v, 4))
    s.median = median(vals)
    s.q1 = quantile(vals, 0.25)
    s.q3 = quantile(vals, 0.75)
    s.iqr = s.q1 === null ? null : s.q3 - s.q1
    if (KIND === 'quantity') {
      s.rel_iqr = s.median === null ? null : (s.median !== 0 ? s.iqr / Math.abs(s.median) : (s.iqr > 0 ? Infinity : 0))
      const ests = live.map(a => a.estimate).filter(Boolean)
      // consensus = per-level median (robust to one outlier); Vincentization = per-level mean, reported alongside
      s.median_quantiles = ests.length ? { p10: median(ests.map(e => e.p10)), p50: median(ests.map(e => e.p50)), p90: median(ests.map(e => e.p90)) } : null
      s.vincentized_mean = ests.length ? { p10: mean(ests.map(e => e.p10)), p50: mean(ests.map(e => e.p50)), p90: mean(ests.map(e => e.p90)) } : null
      s.linear_pool = ests.length ? linearPoolQuantiles(ests) : null
    } else {
      const ps = vals.map(clipP)
      s.log_pool = ps.length ? sigmoid(ps.reduce((t, p) => t + logit(p), 0) / ps.length) : null
      s.linear_pool = ps.length ? vals.reduce((t, p) => t + p, 0) / vals.length : null
    }
  } else if (KIND === 'choice') {
    const first = {}, borda = {}
    for (const id of OPTION_IDS) { first[id] = 0; borda[id] = 0 }
    const m = OPTION_IDS.length
    for (const a of live) {
      if (a.ranking && a.ranking.length) first[a.ranking[0]] += 1
      ;(a.ranking || []).forEach((id, pos) => { borda[id] += (m - 1 - pos) })
    }
    const order = OPTION_IDS.slice().sort((x, y) => (borda[y] - borda[x]) || (first[y] - first[x]) || (OPTION_IDS.indexOf(x) - OPTION_IDS.indexOf(y)))
    s.first_choice_counts = first
    s.borda = borda
    s.borda_order = order
    s.winner = order[0]
    const modal = OPTION_IDS.slice().sort((x, y) => (first[y] - first[x]) || (OPTION_IDS.indexOf(x) - OPTION_IDS.indexOf(y)))[0]
    s.modal_option = modal
    s.modal_share = live.length ? first[modal] / live.length : 0
  }
  return s
}

function sideOf(a, st) {
  if (!a) return 'n/a'
  if (KIND === 'quantity' || KIND === 'probability') {
    const v = valueOf(a)
    if (v === null || st.median === null) return 'n/a'
    return v > st.median ? 'above the median' : (v < st.median ? 'below the median' : 'at the median')
  }
  if (KIND === 'choice') return a.ranking && a.ranking.length ? 'for ' + a.ranking[0] : 'n/a'
  return 'n/a'
}

// Strip agent names and self-identifying phrasing before anything reaches another panelist.
// Only hyphenated agent names: single words (planner, architect, reviewer) are ordinary technical vocabulary.
const NAME_RE = new RegExp('\\b(' + AGENTS.filter(n => n.includes('-')).sort((x, y) => y.length - x.length).map(n => n.replace(/[-]/g, '\\-')).join('|') + ')\\b', 'gi')
function scrub(t) {
  return String(t || '')
    .replace(NAME_RE, 'a panelist')
    .replace(/\bas an? [a-z -]{0,40}(expert|engineer|architect|planner|critic|researcher|auditor|reviewer)\b/gi, 'from my analysis')
    .slice(0, 400)
}

function fmt(x) {
  if (x === null || x === undefined) return 'n/a'
  if (!Number.isFinite(x)) return String(x)
  return String(round(x, Math.abs(x) >= 100 ? 1 : 3))
}

function describeStats(st) {
  const u = FQ.unit ? ' ' + FQ.unit : ''
  if (KIND === 'quantity') {
    const lines = [
      `P50 estimates (sorted, anonymous): ${st.values_sorted.map(fmt).join(', ')}${u}`,
      `Median ${fmt(st.median)}${u}; IQR ${fmt(st.q1)}-${fmt(st.q3)}; relative IQR ${fmt(st.rel_iqr)}`,
    ]
    if (st.median_quantiles) lines.push(`Group quantiles (per-level median of panelist quantiles): P10 ${fmt(st.median_quantiles.p10)}, P50 ${fmt(st.median_quantiles.p50)}, P90 ${fmt(st.median_quantiles.p90)}${u}; Vincentized mean P10 ${fmt(st.vincentized_mean.p10)}, P50 ${fmt(st.vincentized_mean.p50)}, P90 ${fmt(st.vincentized_mean.p90)}${u}`)
    return lines.join('\n')
  }
  if (KIND === 'probability') {
    return [
      `Probabilities (sorted, anonymous): ${st.values_sorted.map(fmt).join(', ')}`,
      `Median ${fmt(st.median)}; IQR ${fmt(st.q1)}-${fmt(st.q3)} (width ${fmt(st.iqr)}); log-odds pool ${fmt(st.log_pool)}; linear pool ${fmt(st.linear_pool)}`,
    ].join('\n')
  }
  if (KIND === 'choice') {
    return [
      `First choices: ${OPTION_IDS.map(id => id + '=' + st.first_choice_counts[id]).join(', ')} (n=${st.n})`,
      `Borda points: ${st.borda_order.map(id => id + '=' + st.borda[id]).join(', ')}; Borda leader ${st.winner}; modal share ${fmt(st.modal_share)}`,
    ].join('\n')
  }
  return `n=${st.n} open answers`
}

// Stopping rules (see delphi-method): convergence on dispersion, stability on movement, hard cap.
const IQR_THRESHOLD = Number.isFinite(Number(A.iqrThreshold)) && Number(A.iqrThreshold) > 0 ? Number(A.iqrThreshold) : (KIND === 'probability' ? 0.10 : 0.25)
const CONSENSUS_SHARE = Number.isFinite(Number(A.consensusShare)) ? Math.min(1, Math.max(0.5, Number(A.consensusShare))) : 0.75
function checkStop(r, st, prevSt, answers, prevAnswers) {
  const thrQ = IQR_THRESHOLD
  const share = CONSENSUS_SHARE
  if (KIND === 'quantity' && st.n_numeric >= 3 && st.rel_iqr !== null && st.rel_iqr <= thrQ) return { stop: true, rule: 'convergence', detail: `relative IQR ${fmt(st.rel_iqr)} <= ${thrQ}` }
  if (KIND === 'probability' && st.n_numeric >= 3 && st.iqr !== null && st.iqr <= thrQ) return { stop: true, rule: 'convergence', detail: `IQR width ${fmt(st.iqr)} <= ${thrQ}` }
  if (KIND === 'choice' && st.n >= 3 && st.modal_share >= share) return { stop: true, rule: 'convergence', detail: `modal first-choice share ${fmt(st.modal_share)} >= ${share}` }
  if (r >= 2 && prevSt) {
    if ((KIND === 'quantity' || KIND === 'probability') && st.median !== null && prevSt.median !== null) {
      const dMed = KIND === 'quantity'
        ? (prevSt.median ? Math.abs(st.median - prevSt.median) / Math.abs(prevSt.median) : Math.abs(st.median - prevSt.median))
        : Math.abs(st.median - prevSt.median)
      const medOk = KIND === 'quantity' ? dMed <= 0.05 : dMed <= 0.025
      let bigMoves = 0
      answers.forEach((a, i) => {
        const v = valueOf(a), pv = valueOf(prevAnswers[i])
        if (v === null || pv === null) return
        const moved = KIND === 'quantity' ? (pv !== 0 ? Math.abs(v - pv) / Math.abs(pv) > 0.10 : v !== pv) : Math.abs(v - pv) > 0.05
        if (moved) bigMoves++
      })
      if (medOk && bigMoves <= 1) return { stop: true, rule: 'stability', detail: `median moved ${fmt(dMed)}${KIND === 'quantity' ? ' (relative)' : ''}, ${bigMoves} panelist(s) moved materially` }
    } else if (KIND === 'choice') {
      let changed = 0
      answers.forEach((a, i) => { const p = prevAnswers[i]; if (a && p && a.ranking && p.ranking && a.ranking[0] !== p.ranking[0]) changed++ })
      if (st.winner === prevSt.winner && changed <= 1) return { stop: true, rule: 'stability', detail: `Borda leader unchanged (${st.winner}), ${changed} first choice(s) changed` }
    } else {
      const moved = answers.filter(a => a && a.moved === true).length
      if (moved <= 1) return { stop: true, rule: 'stability', detail: `${moved} panelist(s) changed position` }
    }
  }
  if (r >= ROUNDS) return { stop: true, rule: 'cap', detail: `round cap ${ROUNDS} reached` }
  return { stop: false }
}

// ---------------- prompts ----------------
function questionBlock() {
  const lines = [`QUESTION: ${FQ.question}`, `Kind: ${KIND}`]
  if (FQ.unit) lines.push(`Unit: ${FQ.unit}`)
  if (FQ.horizon) lines.push(`Horizon: ${FQ.horizon}`)
  if (FQ.resolution) lines.push(`Resolution: ${FQ.resolution}`)
  if (FQ.definitions.length) lines.push('Definitions:\n' + FQ.definitions.map(d => '- ' + d).join('\n'))
  if (KIND === 'choice') lines.push('Options (rank ALL of them by id, best first):\n' + FQ.options.map(o => '- ' + o).join('\n'))
  if (EVIDENCE.length) lines.push('Evidence pack (identical for every panelist; Read these): ' + EVIDENCE.join(', '))
  return lines.join('\n')
}
function kindInstructions() {
  if (KIND === 'quantity') return `Give estimate {p10, p50, p90}${FQ.unit ? ' in ' + FQ.unit : ' and state the unit in estimate.unit'}: an honest 80% interval, never a point. Anchor on a reference class (comparable cases and their outcomes) before adjusting for specifics. confidence = probability the truth lies inside [p10, p90] (well calibrated is about 0.8).`
  if (KIND === 'probability') return 'Give probability in [0, 1] for the event as resolved above. Start from a base rate for the reference class, then adjust. Avoid 0 and 1. confidence = how much you would bet your probability is better than the group median.'
  if (KIND === 'choice') return 'Give ranking: every option id, best first. answer starts with your top option id. confidence = probability your top option is actually best under the stated resolution.'
  return 'Give a direct answer in one paragraph. confidence = probability your answer would survive expert review under the stated resolution.'
}
const PANEL_RULES = 'Rules: you are an anonymous panelist; never name your agent type, role or model in any field (your text is shown to other panelists). Do not spawn subagents and do not run workflows. At most 15 tool calls (Read, Grep, Bash for a quick computation, WebSearch or mcp__exa__web_search_exa for a specific fact) to check facts; no broad research. Return only the structured output.'

function firstPrompt(p) {
  return `You are panelist ${p.label} on a Delphi panel run by the expert-panel workflow (round 1 of up to ${ROUNDS}). Answer independently from your own expertise; nobody else's answer is visible yet.
${p.perspective ? 'Your assigned perspective: ' + p.perspective + '\n' : ''}
${questionBlock()}

${kindInstructions()}
key_arguments: at most 3, each <= 2 lines, each with an evidence pointer. cruxes: what observation would move you by more than 2x (quantity) or 20 points (probability/confidence); prefix "CHECKABLE: " when a lookup (spec number, benchmark, published result, date) could settle it.

${PANEL_RULES}`
}

function revisePrompt(p, prev, packet, r) {
  return `You are panelist ${p.label} on a Delphi panel run by the expert-panel workflow, round ${r} of up to ${ROUNDS}.
${p.perspective ? 'Your assigned perspective: ' + p.perspective + '\n' : ''}
${questionBlock()}

YOUR PREVIOUS ANSWER (round ${r - 1}):
${JSON.stringify(prev || { note: 'you did not answer last round; answer fresh' }, null, 1).slice(0, 3000)}

ANONYMOUS FEEDBACK PACKET:
${packet}

Revise or hold. Rules:
- If you move, set moved=true and name in moved_because the specific argument or evidence ruling that moved you. Moving toward the median without a new reason is herding: do not.
- If you hold a position outside the IQR (or against the majority), give hold_reason with a reason NOT already in the packet.
- Evidence rulings marked "chair's note" come from a fact-checker; treat a contradicted crux as settled unless you have stronger evidence.
${kindInstructions()}

${PANEL_RULES}`
}

const CLUSTER_SCHEMA = {
  type: 'object',
  properties: {
    clusters: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string', description: 'neutral restatement, <= 2 lines, no panelist labels' },
          side: { type: 'string' },
          members: { type: 'array', items: { type: 'string' } },
        },
        required: ['claim', 'side', 'members'],
      },
    },
    checkable_cruxes: {
      type: 'array',
      items: {
        type: 'object',
        properties: { crux: { type: 'string' }, check: { type: 'string', description: 'the concrete lookup that settles it' } },
        required: ['crux', 'check'],
      },
    },
  },
  required: ['clusters', 'checkable_cruxes'],
}
const RULING_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['supported', 'partially_supported', 'contradicted', 'unverifiable'] },
    ruling: { type: 'string', description: '<= 2 lines stating what the evidence says, with the number or date' },
    sources: {
      type: 'array',
      items: {
        type: 'object',
        properties: { url: { type: 'string' }, date: { type: 'string' }, quote: { type: 'string', description: 'under 15 words' } },
        required: ['url'],
      },
    },
  },
  required: ['verdict', 'ruling'],
}

// ---------------- rounds ----------------
const rounds = []
const rulings = []
const ruledCruxes = []
let answers = new Array(panel.length).fill(null)
let prevAnswers = null
let prevStats = null
let packet = ''
let stop = { stop: false }
let firstStats = null

for (let r = 1; r <= ROUNDS; r++) {
  if (r > 1 && lowBudget(60000)) { stop = { stop: true, rule: 'budget', detail: `token budget nearly exhausted before round ${r}` }; note(stop.detail); break }
  const ph = r === 1 ? 'Round 1' : 'Revise'
  phase(ph)
  const raw = await parallel(panel.map((p, i) => () => call(
    r === 1 ? firstPrompt(p) : revisePrompt(p, prevAnswers[i], packet, r),
    { label: `r${r}:${p.label}`, phase: ph, agentType: p.agentType, model: p.model, schema: answerSchema(r > 1) },
  )))
  let carried = 0
  const cur = raw.map((a, i) => {
    const n = normalizeAnswer(a, `r${r}:${panel[i].label}`)
    if (n) return n
    if (prevAnswers && prevAnswers[i]) { carried++; return Object.assign({}, prevAnswers[i], { carried: true, moved: false }) }
    return null
  })
  const responded = raw.filter(Boolean).length
  if (carried) note(`round ${r}: ${carried} panelist(s) did not answer; their previous answer is carried forward and flagged`)
  if (r === 1 && responded < 3) {
    return { started: true, completed: false, reason: `only ${responded} of ${panel.length} panelists answered round 1; a panel needs at least 3`, frame: FQ, kind: KIND, panel: panel.map(p => ({ label: p.label, agentType: p.agentType })), notes }
  }
  answers = cur
  phase('Feedback')
  const st = computeStats(answers)
  if (r === 1) firstStats = st
  const movedCount = r > 1 ? answers.filter(a => a && a.moved === true && !a.carried).length : null
  const newReasons = r > 1 ? answers.filter(a => a && a.moved === true && !a.carried && String(a.moved_because || '').trim().length >= 15).length : null
  stop = checkStop(r, st, prevStats, answers, prevAnswers || [])

  // Arguments and cruxes for the next packet (skipped after the final round).
  let clusters = [], checkable = []
  if (!stop.stop) {
    const argItems = []
    answers.forEach((a, i) => {
      if (!a || a.carried) return
      for (const t of a.key_arguments) argItems.push({ panelist: panel[i].label, side: sideOf(a, st), text: scrub(t) })
    })
    const cruxItems = []
    answers.forEach((a, i) => { if (a && !a.carried) for (const c of a.cruxes) cruxItems.push({ panelist: panel[i].label, text: scrub(c) }) })
    let summarized = null
    if (argItems.length > CLUSTER_THRESHOLD) {
      summarized = await call(
        `Cluster the anonymous arguments from round ${r} of a Delphi panel and pick out checkable cruxes. Do not add facts, do not judge who is right, do not spawn subagents. Keep each cluster claim neutral, <= 2 lines, with no panelist labels or agent names; members lists the P-labels that made it.
Question: ${FQ.question}

ARGUMENTS (label | side | text):
${argItems.map(x => `${x.panelist} | ${x.side} | ${x.text}`).join('\n')}

CRUXES (label | text):
${cruxItems.map(x => `${x.panelist} | ${x.text}`).join('\n') || 'none'}

checkable_cruxes: only factual questions a lookup could settle (a spec number, a benchmark result, a published figure, a date, a documented behaviour), each with the concrete check. At most 5.`,
        { label: `r${r}:cluster`, phase: 'Feedback', agentType: 'source-summarizer', schema: CLUSTER_SCHEMA },
      )
      if (!summarized) note(`round ${r}: argument clustering failed; raw de-duplicated arguments used`)
    }
    if (summarized && Array.isArray(summarized.clusters) && summarized.clusters.length) {
      clusters = summarized.clusters.map(c => ({ claim: scrub(c.claim), side: c.side, count: (c.members || []).length }))
    } else {
      clusters = dedupTexts(argItems, x => x.text, 0.7).map(x => ({ claim: x.text, side: x.side, count: 1 }))
    }
    // checkable cruxes: chair-marked by panelists plus summarizer picks, minus those already ruled on
    const candidates = []
    for (const c of cruxItems) if (/^\s*checkable\s*:/i.test(c.text)) candidates.push({ crux: c.text.replace(/^\s*checkable\s*:\s*/i, ''), check: '' })
    if (summarized && Array.isArray(summarized.checkable_cruxes)) for (const c of summarized.checkable_cruxes) candidates.push({ crux: scrub(c.crux), check: c.check || '' })
    const fresh = dedupTexts(candidates, x => x.crux, 0.6).filter(c => !ruledCruxes.some(s => jaccard(s, c.crux) >= 0.6))
    if (CHECK_CRUXES && MAX_CRUX_CHECKS > 0) {
      checkable = fresh.slice(0, MAX_CRUX_CHECKS)
      if (fresh.length > checkable.length) note(`round ${r}: ${fresh.length - checkable.length} checkable crux(es) not fact-checked (maxCruxChecks=${MAX_CRUX_CHECKS}): ${fresh.slice(MAX_CRUX_CHECKS).map(c => c.crux.slice(0, 60)).join(' | ')}`)
    } else if (fresh.length) {
      note(`round ${r}: crux checking disabled; ${fresh.length} checkable crux(es) left unsettled`)
    }
    if (checkable.length) {
      const res = await parallel(checkable.map((c, k) => () => call(
        `Settle one factual crux raised in an expert panel. Find the primary source (official docs, spec, paper, dataset, vendor benchmark with method) and state what it says. Quotes under 15 words. Run \`date\` first and flag the source as stale if it predates a known relevant change. If it cannot be settled in about 24 tool calls, return unverifiable and say which source would settle it. Do not spawn subagents.
Panel question (context only): ${FQ.question}
CRUX: ${c.crux}
${c.check ? 'Suggested check: ' + c.check : ''}`,
        { label: `r${r}:crux${k + 1}`, phase: 'Feedback', agentType: 'fact-checker', schema: RULING_SCHEMA },
      )))
      res.forEach((x, k) => {
        ruledCruxes.push(checkable[k].crux)
        if (x) rulings.push({ round: r, crux: checkable[k].crux, verdict: x.verdict, ruling: x.ruling, sources: (x.sources || []).slice(0, 3) })
        else note(`round ${r}: fact-check of crux "${checkable[k].crux.slice(0, 60)}" failed`)
      })
    }
    const numeric = KIND === 'quantity' || KIND === 'probability'
    const above = numeric ? clusters.filter(c => /above/i.test(c.side)).slice(0, 3) : []
    const below = numeric ? clusters.filter(c => /below/i.test(c.side)).slice(0, 3) : []
    const other = clusters.filter(c => !above.includes(c) && !below.includes(c)).slice(0, numeric ? 3 : 8)
    const dropped = clusters.length - above.length - below.length - other.length
    if (dropped > 0) note(`round ${r}: packet capped; ${dropped} argument cluster(s) not shown to panelists`)
    const argLines = (xs, h) => xs.length ? `${h}\n${xs.map(c => `- ${c.claim}${c.count > 1 ? ' (' + c.count + ' panelists)' : ''}${KIND === 'choice' ? ' [' + c.side + ']' : ''}`).join('\n')}` : ''
    const newRulings = rulings.filter(x => x.round === r)
    packet = [
      `Round ${r} results (n=${st.n}, anonymous).`,
      describeStats(st),
      argLines(above, 'Strongest arguments from above the median:'),
      argLines(below, 'Strongest arguments from below the median:'),
      argLines(other, numeric ? 'Other arguments:' : 'Arguments raised:'),
      cruxItems.length ? 'Cruxes raised:\n' + dedupTexts(cruxItems, x => x.text, 0.6).slice(0, 6).map(c => '- ' + c.text.replace(/^\s*checkable\s*:\s*/i, '')).join('\n') : '',
      newRulings.length ? "Chair's notes (evidence rulings from a fact-checker):\n" + newRulings.map(x => `- "${x.crux.slice(0, 160)}" -> ${x.verdict}: ${x.ruling}${x.sources[0] ? ' (' + x.sources[0].url + ')' : ''}`).join('\n') : '',
    ].filter(Boolean).join('\n\n')
  }

  rounds.push({
    round: r,
    n: st.n,
    responded,
    carried,
    moved: movedCount,
    new_reasons_cited: newReasons,
    stats: JSON.parse(JSON.stringify(st, (k, v) => (typeof v === 'number' ? round(v, 4) : v))),
    stop_check: stop.stop ? stop.rule + ': ' + stop.detail : 'continue',
    packet: packet && !stop.stop ? packet : '',
  })
  log(`round ${r}: ${(describeStats(st).split('\n')[1] || describeStats(st).split('\n')[0])}${stop.stop ? ' -> stop (' + stop.rule + ')' : ''}`)
  if (stop.stop) break
  prevStats = st
  prevAnswers = answers
}

// ---------------- aggregate, minority, herding ----------------
const finalStats = computeStats(answers)
const lastRound = rounds.length ? rounds[rounds.length - 1].round : 0
let herding = { checked: lastRound >= 2, label: 'not applicable (single round)' }
if (lastRound >= 2 && firstStats) {
  const totalNewReasons = rounds.slice(1).reduce((t, x) => t + (x.new_reasons_cited || 0), 0)
  if (KIND === 'quantity' || KIND === 'probability') {
    const i0 = firstStats.iqr, i1 = finalStats.iqr
    const shrink = i0 && i0 > 0 ? 1 - i1 / i0 : 0
    const conform = shrink > 0.5 && totalNewReasons < 2
    herding = { checked: true, iqr_round1: round(i0, 4), iqr_final: round(i1, 4), shrink: round(shrink, 3), new_reasons_cited: totalNewReasons, label: conform ? 'convergence by conformity' : 'earned or no material convergence' }
  } else if (KIND === 'choice') {
    const gain = finalStats.modal_share - firstStats.modal_share
    const conform = gain > 0.3 && totalNewReasons < 2
    herding = { checked: true, modal_share_round1: round(firstStats.modal_share, 3), modal_share_final: round(finalStats.modal_share, 3), new_reasons_cited: totalNewReasons, label: conform ? 'convergence by conformity' : 'earned or no material convergence' }
  } else {
    const moved = rounds.slice(1).reduce((t, x) => t + (x.moved || 0), 0)
    herding = { checked: true, moved_total: moved, new_reasons_cited: totalNewReasons, label: moved >= 2 && totalNewReasons < 2 ? 'convergence by conformity' : 'earned or no material convergence' }
  }
}

const minority = []
answers.forEach((a, i) => {
  if (!a) return
  let outside = false
  if (KIND === 'quantity' || KIND === 'probability') {
    // material dissent only: outside the final IQR AND farther from the median than the convergence threshold
    // (the min and max always sit outside a type-7 IQR, even under tight consensus)
    const v = valueOf(a), med = finalStats.median
    if (v !== null && med !== null && finalStats.q1 !== null && (v < finalStats.q1 || v > finalStats.q3)) {
      const dist = KIND === 'quantity' ? (med !== 0 ? Math.abs(v - med) / Math.abs(med) : Math.abs(v)) : Math.abs(v - med)
      outside = dist > IQR_THRESHOLD
    }
  } else if (KIND === 'choice') {
    outside = !!(a.ranking && a.ranking.length && a.ranking[0] !== finalStats.winner)
  }
  if (outside) minority.push({ panelist: panel[i].label, position: KIND === 'choice' ? a.ranking[0] : valueOf(a), estimate: a.estimate || undefined, strongest_argument: scrub(a.key_arguments[0] || ''), hold_reason: a.hold_reason || '', cruxes: a.cruxes.slice(0, 2) })
})

const aggregate = { kind: KIND, unit: KIND === 'quantity' ? (FQ.unit || undefined) : undefined, n: finalStats.n }
if (KIND === 'quantity') {
  aggregate.consensus_quantiles = finalStats.median_quantiles
  aggregate.vincentized_mean_quantiles = finalStats.vincentized_mean
  aggregate.linear_pool_quantiles = finalStats.linear_pool
  aggregate.median = finalStats.median
  aggregate.iqr = [finalStats.q1, finalStats.q3]
  aggregate.rel_iqr = finalStats.rel_iqr
  aggregate.stable_dissent = stop.rule === 'stability' && finalStats.rel_iqr > IQR_THRESHOLD
} else if (KIND === 'probability') {
  aggregate.log_pool = finalStats.log_pool
  aggregate.linear_pool = finalStats.linear_pool
  aggregate.median = finalStats.median
  aggregate.iqr = [finalStats.q1, finalStats.q3]
  aggregate.stable_dissent = stop.rule === 'stability' && finalStats.iqr > IQR_THRESHOLD
} else if (KIND === 'choice') {
  aggregate.winner = finalStats.winner
  aggregate.borda = finalStats.borda
  aggregate.first_choice_counts = finalStats.first_choice_counts
  aggregate.modal_share = finalStats.modal_share
}
const aggregateOut = JSON.parse(JSON.stringify(aggregate, (k, v) => (typeof v === 'number' ? round(v, 4) : v)))

// ---------------- Synthesize ----------------
phase('Synthesize')
const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    consensus: { type: 'string', description: 'the answer to the framed question in its units and horizon, with the uncertainty' },
    dissent: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          position: { type: 'string' },
          panelists: { type: 'array', items: { type: 'string' } },
          strongest_argument: { type: 'string' },
          crux: { type: 'string' },
          deciding_evidence: { type: 'string' },
        },
        required: ['position', 'strongest_argument', 'crux'],
      },
    },
    cruxes: { type: 'array', items: { type: 'string' } },
    confidence: {
      type: 'object',
      properties: {
        label: { type: 'string', enum: ['earned', 'conformist', 'split'] },
        level: { type: 'number', minimum: 0, maximum: 1 },
        reason: { type: 'string' },
      },
      required: ['label', 'level', 'reason'],
    },
    report_path: { type: 'string' },
  },
  required: ['consensus', 'dissent', 'confidence', 'report_path'],
}
const recordForChair = rounds.map(x => ({ round: x.round, n: x.n, responded: x.responded, carried: x.carried, moved: x.moved, new_reasons_cited: x.new_reasons_cited, stats: x.stats, stop_check: x.stop_check }))
const finalAnswers = answers.map((a, i) => a && { label: panel[i].label, answer: scrub(a.answer).slice(0, 600), estimate: a.estimate, probability: a.probability, ranking: a.ranking, key_arguments: a.key_arguments.map(scrub), cruxes: a.cruxes.map(scrub).slice(0, 3), confidence: a.confidence, moved_because: a.moved_because, hold_reason: a.hold_reason, carried: a.carried || undefined }).filter(Boolean)

const synth = await call(
  `You are the expert-panel chair in SYNTHESIS mode for the expert-panel workflow. The rounds already ran; all statistics below were computed in code and are authoritative: quote them, do not recompute them differently. Do not spawn panelists, do not run more rounds, do not launch workflows.

Write these files (create the directory): ${RUN_DIR}/question.md (framed question), ${RUN_DIR}/rounds.md (one table per round: round | n | median | IQR | relative IQR or shares | moved | new reasons cited), ${RUN_DIR}/packets/r<k>.md (the packets below, verbatim), ${RUN_DIR}/report.md (consensus, convergence table, stopping rule with its numbers, herding verdict, minority report, cruxes, evidence rulings, method). Return report_path=${RUN_DIR}/report.md.

${questionBlock()}
Panel composition (do not map labels to types in any file): ${panel.map(p => p.agentType + (p.model ? '/' + p.model : '')).join(', ')}

STOPPING RULE: ${stop.rule || 'cap'}: ${stop.detail || ''}
AGGREGATE (code): ${JSON.stringify(aggregateOut)}
HERDING CHECK (code): ${JSON.stringify(herding)}
MINORITY (code; positions outside the final IQR and farther than the threshold from the median, or against the winner): ${JSON.stringify(minority).slice(0, 4000)}
ROUND RECORDS: ${JSON.stringify(recordForChair).slice(0, 12000)}
FINAL ANSWERS (anonymous): ${JSON.stringify(finalAnswers).slice(0, 16000)}
EVIDENCE RULINGS: ${JSON.stringify(rulings).slice(0, 5000)}
PACKETS:
${rounds.filter(x => x.packet).map(x => `--- packet after round ${x.round} ---\n${x.packet}`).join('\n').slice(0, 16000)}

Synthesis rules:
- Quantities: consensus = consensus_quantiles, the per-level median P10/P50/P90 (call it that, not Vincentized); also report vincentized_mean_quantiles (per-level mean) under that name and the linear-pool band, which is the honest band when dissent is stable. Probabilities: the log-odds pool (no extremizing: panelists share one evidence pack). Choice: the Borda winner with first-choice shares.
- confidence.label: "conformist" if the herding check says conformity; "split" if the stopping rule was stability with dispersion still above threshold or the minority holds a distinct checkable crux; otherwise "earned".
- Every dissent entry: its strongest argument, its crux, and the evidence that would decide it.
- Never report agreement the rounds did not produce.`,
  { label: 'chair-synthesis', phase: 'Synthesize', agentType: 'expert-panel-chair', schema: SYNTH_SCHEMA },
)

let consensus, dissent, confidence, reportPath
if (synth) {
  consensus = synth.consensus
  dissent = synth.dissent || []
  confidence = synth.confidence
  reportPath = synth.report_path || `${RUN_DIR}/report.md`
} else {
  note('synthesis: chair unavailable; consensus assembled from code aggregates, no report file written')
  const u = FQ.unit ? ' ' + FQ.unit : ''
  if (KIND === 'quantity' && aggregateOut.consensus_quantiles) consensus = `P10 ${fmt(aggregateOut.consensus_quantiles.p10)}, P50 ${fmt(aggregateOut.consensus_quantiles.p50)}, P90 ${fmt(aggregateOut.consensus_quantiles.p90)}${u} (per-level median; Vincentized mean P50 ${fmt(aggregateOut.vincentized_mean_quantiles.p50)}; linear pool P10-P90 ${fmt(aggregateOut.linear_pool_quantiles.p10)}-${fmt(aggregateOut.linear_pool_quantiles.p90)})`
  else if (KIND === 'probability') consensus = `pooled probability ${fmt(aggregateOut.log_pool)} (log-odds pool; median ${fmt(aggregateOut.median)}, IQR ${fmt(aggregateOut.iqr[0])}-${fmt(aggregateOut.iqr[1])})`
  else if (KIND === 'choice') consensus = `Borda winner ${aggregateOut.winner}; first choices ${JSON.stringify(aggregateOut.first_choice_counts)}`
  else consensus = 'no synthesis available; see final answers'
  dissent = minority.map(m => ({ position: String(m.position), panelists: [m.panelist], strongest_argument: m.strongest_argument, crux: (m.cruxes[0] || ''), deciding_evidence: '' }))
  const split = !!aggregateOut.stable_dissent || minority.length >= 2
  confidence = { label: herding.label === 'convergence by conformity' ? 'conformist' : (split ? 'split' : 'earned'), level: split ? 0.5 : 0.65, reason: 'computed without chair synthesis' }
  reportPath = null
}

return {
  started: true,
  completed: true,
  question: FQ,
  kind: KIND,
  panel: panel.map(p => ({ label: p.label, agentType: p.agentType, model: p.model, perspective: p.perspective })),
  consensus,
  aggregate: aggregateOut,
  // with a report on disk, return digests only (full rounds, packets and answers are in run_dir)
  rounds: reportPath ? recordForChair.map(x => ({ round: x.round, n: x.n, moved: x.moved, stop_check: x.stop_check })) : rounds,
  stop: { rule: stop.rule || 'cap', detail: stop.detail || '', after_round: lastRound },
  herding,
  dissent,
  minority: reportPath ? minority.map(m => ({ panelist: m.panelist, position: m.position })) : minority,
  crux_rulings: rulings,
  confidence,
  final_answers: reportPath ? undefined : finalAnswers,
  report_path: reportPath,
  run_dir: RUN_DIR,
  notes,
}
