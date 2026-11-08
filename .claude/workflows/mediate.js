export const meta = {
  name: 'mediate',
  description: 'Mediator vote: diverse voters solve independently, cross-critique anonymised solutions blind, the declared rule (Schulze default; Borda, plurality, approval, log pool) is tallied in code with margin and robustness checks, near-ties get one debate round, and the mediator synthesises the winner with grafts',
  whenToUse: 'A judgment call with several defensible answers where one must be chosen with an auditable rationale (architecture choice, strategy, proof approach, interpretation). Not for checkable questions; verify those instead. Main thread only. args {problem, voters?: [{agentType, model? and effort? (general-purpose only; model opus|sonnet|haiku), perspective?, weight?}], method?: schulze|borda|plurality|approval|logpool, criteria?, nearTie?, debate?=true, outDir?, runTag?}',
  phases: [
    { title: 'Solve', detail: 'every voter answers independently in a fixed solution schema' },
    { title: 'Critique+Rank', detail: 'anonymised S1..Sn shown blind, in a rotated order per voter; full ranking, approvals, P(best) per solution, strongest point and flaw per solution' },
    { title: 'Tally', detail: 'declared rule computed in code, plus every other rule, margin, self-preference (no-self) and leave-one-out checks' },
    { title: 'Debate', detail: 'only on a near-tie: the two top authors rebut each other, then all voters re-vote pairwise' },
    { title: 'Synthesize', detail: 'mediator writes the final answer from the winner, grafting compatible runner-up strengths, and cross-checks the tally with tally.py' },
  ],
}

// ---------------------------------------------------------------------------- constants
const METHODS = ['schulze', 'borda', 'plurality', 'approval', 'logpool']
const METHOD_ALIASES = { condorcet: 'schulze', 'log-pool': 'logpool', log_pool: 'logpool', 'log pool': 'logpool', logarithmic: 'logpool', 'opinion-pool': 'logpool' }
// Near-tie thresholds per rule; identical to .claude/skills/mediator-voting/scripts/tally.py NEAR_TIE.
// Every rule reproduces tally.py (schulze: unbeaten tiers + strongest-path margin). A Condorcet winner's strongest-path margin is
// always > 0.5, so schulze also reports pairwise_margin = (d[w][r] - d[r][w]) / W (direct counts) as an extra near-tie trigger.
const NEAR_TIE = { plurality: 0.2, approval: 0.2, borda: 0.1, schulze: 0.2, logpool: 0.1 }
const CLIP = 0.02
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']
const MODELS = ['opus', 'sonnet', 'haiku']   // tier aliases; only general-purpose voters take a per-call model/effort
const REVOTE_NEAR_TIE = 0.2      // debate re-vote still a near-tie below this weighted-majority margin (mediator-voting section 8)
const MIN_VOTERS = 3
const MAX_VOTERS = 9
const ANSWER_CAP = 9000          // chars of one answer shown to voters
const DEBATE_MIN_BUDGET = 60000  // tokens; below this (with a budget set) the debate round is skipped
const DEFAULT_CRITERIA = 'Correctness first (it must actually solve the stated problem under its stated constraints), then robustness to failure and to wrong assumptions, then simplicity and total cost (build, run, change). State any extra criterion you apply.'
const DEFAULT_VOTERS = [
  { agentType: 'computer-science-expert', perspective: 'Formal guarantees: correctness argument, complexity and worst case, known impossibility results and lower bounds.' },
  { agentType: 'mathematics-expert', perspective: 'Rigor: state every assumption, prove or bound the decisive claim, hunt for counterexamples to the obvious answer.' },
  { agentType: 'architect', perspective: 'System level: failure modes, operability, migration and evolution cost, blast radius, what breaks at 10x scale.' },
  { agentType: 'first-principles-decomposer', perspective: 'Separate hard constraints from conventions, rebuild the option space from invariants, and challenge the framing of the question itself.' },
  { agentType: 'general-purpose', model: 'sonnet', effort: 'high', perspective: 'Pragmatic practitioner: the simplest option that works in production now; flag over-engineering and hidden operational cost.' },
]
// Distinctive (hyphenated) stack agent names redacted from solutions before voters see them.
const STACK_AGENTS = ['concurrent-dispatcher', 'swarm-coordinator', 'mesh-router', 'ensemble-assembler', 'plan-critic', 'adversarial-verifier',
  'code-quality-analyst', 'quick-researcher', 'deep-researcher', 'browser-operator', 'computer-operator', 'paper-researcher', 'source-summarizer',
  'file-summarizer', 'computer-graphics-expert', 'computer-science-expert', 'quantum-computing-expert', 'rust-expert', 'cpp-expert', 'go-expert',
  'haskell-expert', 'julia-expert', 'java-expert', 'kotlin-expert', 'python-expert', 'typescript-expert', 'container-expert', 'mathematics-expert', 'physics-expert',
  'graphic-design-expert', 'vector-artist',
  'cross-domain-synthesizer', 'expert-panel-chair', 'debate-moderator', 'analogy-mapper', 'first-principles-decomposer', 'general-chat',
  'stack-tuner', 'agent-architect']
// Agent names that are also ordinary technical terms: redacted only as "<name> agent" / "<name> subagent", never in plain prose.
const COMMON_AGENT_TERMS = ['general-purpose', 'quality-control', 'fact-checker', 'web-crawler', 'web-scraper', 'web-searcher', 'code-optimizer',
  'security-auditor', 'image-editor', 'image-generator']
const MODEL_WORDS = ['claude', 'anthropic', 'opus', 'sonnet', 'haiku', 'fable']
const ROLE_RE = /\b(?:as|speaking as|wearing my)\s+(?:an?\s+|the\s+|your\s+)?(?:[\w-]+\s+){0,3}?(?:expert|mathematician|physicist|architect|engineer|scientist|theorist|decomposer|practitioner|researcher|voter|generalist)\b\s*[,:]?\s*/gi

// ---------------------------------------------------------------------------- helpers
function fnv1a(s) {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 }
  return (h >>> 0).toString(16).padStart(8, '0')
}
function slugify(s) {
  const words = String(s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean).slice(0, 6)
  return (words.join('-').slice(0, 40) || 'decision') + '-' + fnv1a(String(s)).slice(0, 6)
}
function clip(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n) + ' [truncated ' + (s.length - n) + ' chars]' : s }
function isBlank(v) { return v === null || v === undefined || (typeof v === 'string' && !v.trim()) }
function round4(x) { return Math.round(x * 1e4) / 1e4 }
function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0 }
function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }
function list(a) { return (Array.isArray(a) ? a : []).map(x => String(x).trim()).filter(Boolean) }
function bullets(a) { const l = list(a); return l.length ? l.map(x => '- ' + x).join('\n') : '- (none given)' }
function labelNum(l) { return parseInt(String(l).slice(1), 10) }
async function call(prompt, opts) {
  try {
    const value = await agent(prompt, opts)
    return { value, error: isBlank(value) ? (value == null ? 'agent returned null' : 'agent returned empty text') : null }
  } catch (e) {
    return { value: null, error: 'agent threw: ' + String(e && e.message ? e.message : e).slice(0, 300) }
  }
}
function parseArgs(raw) {
  if (raw === undefined || raw === null || raw === '') return { ok: true, value: {} }
  if (typeof raw === 'string') {
    const t = raw.trim()
    if (t.startsWith('{')) { try { return { ok: true, value: JSON.parse(t) } } catch (e) { return { ok: false, error: 'args looks like JSON but does not parse: ' + e.message } } }
    return { ok: true, value: { problem: t } }   // a bare string is the problem itself
  }
  if (typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, error: 'args must be an object' }
  return { ok: true, value: raw }
}

// ---------------------------------------------------------------------------- voting math (mirrors tally.py)
// Ballot: {voter, weight, tiers: [[label, ...], ...] best first, approvals: [label], p: {label: prob} | null, author_of: label | null}
function tiersOf(b, cands, drop) {
  const out = []
  const placed = new Set()
  for (const g of b.tiers) {
    const gg = g.filter(c => cands.includes(c) && !placed.has(c) && c !== drop)
    if (gg.length) { out.push(gg); gg.forEach(c => placed.add(c)) }
  }
  const rest = cands.filter(c => !placed.has(c) && c !== drop)
  if (rest.length) out.push(rest)
  return out
}
function zeros(cands) { const s = {}; cands.forEach(c => { s[c] = 0 }); return s }
function plurality(B, cands, noSelf) {
  const s = zeros(cands)
  for (const b of B) {
    const t = tiersOf(b, cands, noSelf ? b.author_of : null)
    if (t.length) for (const c of t[0]) s[c] += b.weight / t[0].length
  }
  return s
}
function borda(B, cands, noSelf) {
  // n-1 points for first ... 0 for last; tied candidates share the average; no-self gives the own solution the neutral midpoint.
  const n = cands.length
  const s = zeros(cands)
  for (const b of B) {
    const own = noSelf ? b.author_of : null
    let pos = 0
    for (const g of tiersOf(b, cands, null)) {
      let pts = 0
      for (let i = 0; i < g.length; i++) pts += n - 1 - (pos + i)
      pts /= g.length
      for (const c of g) s[c] += b.weight * (c === own ? (n - 1) / 2 : pts)
      pos += g.length
    }
  }
  return s
}
function approval(B, cands, noSelf) {
  const s = zeros(cands)
  for (const b of B) {
    const own = noSelf ? b.author_of : null
    for (const c of [...new Set(b.approvals)]) if (c in s && c !== own) s[c] += b.weight
  }
  return s
}
function pairwise(B, cands, noSelf) {
  // d[x][y] = total weight of voters ranking x strictly above y; pairs involving a voter's own solution abstain under no-self.
  const d = {}
  cands.forEach(x => { d[x] = zeros(cands) })
  for (const b of B) {
    const own = noSelf ? b.author_of : null
    const rank = {}
    tiersOf(b, cands, null).forEach((g, i) => g.forEach(c => { rank[c] = i }))
    for (const x of cands) for (const y of cands) if (x !== y && x !== own && y !== own && rank[x] < rank[y]) d[x][y] += b.weight
  }
  return d
}
function schulze(B, cands, noSelf) {
  // Winning-votes link strength, then Floyd-Warshall widest paths (intermediate i in the outer loop).
  const d = pairwise(B, cands, noSelf)
  const p = {}
  cands.forEach(x => { p[x] = zeros(cands); cands.forEach(y => { if (x !== y && d[x][y] > d[y][x]) p[x][y] = d[x][y] }) })
  for (const i of cands) for (const j of cands) {
    if (j === i) continue
    for (const k of cands) {
      if (k === i || k === j) continue
      p[j][k] = Math.max(p[j][k], Math.min(p[j][i], p[i][k]))
    }
  }
  // Schulze ranking: x beats y iff p[x][y] > p[y][x] (a strict partial order). Each tier is the set of
  // remaining candidates beaten by no remaining candidate; the first tier is the Schulze winner set.
  // (A "count of strongest-path wins" score is NOT equivalent: in 2xA>B>C, 2xB>C>A, 1xC>A>B it names B
  // alone although A and B are both unbeaten.)
  const tiers = []
  let rest = cands.slice()
  while (rest.length) {
    let top = rest.filter(x => rest.every(y => y === x || p[x][y] >= p[y][x]))
    if (!top.length) top = rest.slice()   // unreachable: the beats relation is transitive
    tiers.push(top.slice().sort(cmp))
    rest = rest.filter(x => !top.includes(x))
  }
  const beats = {}
  cands.forEach(x => { beats[x] = cands.filter(y => y !== x && p[x][y] > p[y][x]).length })
  const condorcet = cands.find(x => cands.every(y => y === x || d[x][y] > d[y][x])) || null
  return { tiers, scores: beats, pairwise: d, strongest_paths: p, condorcet_winner: condorcet }
}
function logpool(B, cands, noSelf) {
  // Weighted geometric pool of P(best): clip to [CLIP, 1-CLIP], renormalise per voter, mean of logs over voters who rated s, softmax.
  const acc = {}
  cands.forEach(c => { acc[c] = [0, 0] })
  for (const b of B) {
    if (!b.p) continue
    const pc = {}
    for (const [k, v] of Object.entries(b.p)) if (k in acc) pc[k] = Math.min(1 - CLIP, Math.max(CLIP, v))
    const keys = Object.keys(pc)
    if (!keys.length) continue
    const z = keys.reduce((a, k) => a + pc[k], 0)
    const own = noSelf ? b.author_of : null
    for (const k of keys) {
      if (k === own) continue
      acc[k][0] += b.weight * Math.log(pc[k] / z)
      acc[k][1] += b.weight
    }
  }
  const known = cands.filter(c => acc[c][1] > 0)
  const out = zeros(cands)
  if (!known.length) return out
  const score = {}
  known.forEach(c => { score[c] = acc[c][0] / acc[c][1] })
  const m = Math.max(...known.map(c => score[c]))
  let z = 0
  known.forEach(c => { out[c] = Math.exp(score[c] - m); z += out[c] })
  known.forEach(c => { out[c] /= z })
  return out
}
function order(scores) {
  const keys = Object.keys(scores).sort((a, b) => (scores[b] - scores[a]) || cmp(a, b))
  const out = []
  for (const c of keys) {
    if (out.length && Math.abs(scores[out[out.length - 1][0]] - scores[c]) < 1e-9) out[out.length - 1].push(c)
    else out.push([c])
  }
  return out
}
function roundMap(m) { const o = {}; Object.keys(m).forEach(k => { o[k] = typeof m[k] === 'object' ? roundMap(m[k]) : round4(m[k]) }); return o }
function run(B, cands, method, noSelf) {
  const W = B.reduce((a, b) => a + b.weight, 0) || 1
  const n = cands.length
  let s
  let sch = null
  if (method === 'plurality') s = plurality(B, cands, noSelf)
  else if (method === 'borda') s = borda(B, cands, noSelf)
  else if (method === 'approval') s = approval(B, cands, noSelf)
  else if (method === 'schulze') { sch = schulze(B, cands, noSelf); s = sch.scores }
  else s = logpool(B, cands, noSelf)
  const tiers = sch ? sch.tiers : order(s)
  const top = tiers[0]
  let runner = top.length > 1 ? top[1] : (tiers.length > 1 ? tiers[1][0] : null)
  if (sch && top.length === 1 && tiers.length > 1) {
    // Schulze runner-up: the second-tier candidate with the weakest strongest-path deficit against the winner.
    const w = top[0]
    runner = tiers[1].slice().sort((x, y) => ((sch.strongest_paths[w][x] - sch.strongest_paths[x][w]) - (sch.strongest_paths[w][y] - sch.strongest_paths[y][w])) || cmp(x, y))[0]
  }
  let margin
  if (runner === null) margin = 1
  else if (top.length > 1) margin = 0
  else if (method === 'plurality' || method === 'approval') margin = (s[top[0]] - s[runner]) / W
  else if (method === 'borda') margin = (s[top[0]] - s[runner]) / (W * Math.max(1, n - 1))
  else if (method === 'schulze') margin = (sch.strongest_paths[top[0]][runner] - sch.strongest_paths[runner][top[0]]) / W   // as tally.py; > 0.5 for any Condorcet winner
  else margin = s[top[0]] - s[runner]
  const res = { method, scores: roundMap(s), ranking: tiers, winner: top.length === 1 ? top[0] : null, tie: top.length > 1 ? top : [], runner_up: runner, margin: round4(margin), near_tie_threshold: NEAR_TIE[method] }
  if (sch) { res.condorcet_winner = sch.condorcet_winner; res.pairwise = roundMap(sch.pairwise); res.strongest_paths = roundMap(sch.strongest_paths) }
  if (sch && top.length === 1 && runner !== null) res.pairwise_margin = round4((sch.pairwise[top[0]][runner] - sch.pairwise[runner][top[0]]) / W)
  return res
}
function pairTally(votes, a, b, method, exclude) {
  // Debate re-vote between a and b: weighted majority, or for logpool a 2-way geometric pool of p_prefer.
  let wa = 0
  let wb = 0
  let la = 0
  let lb = 0
  let lw = 0
  for (const v of votes) {
    if (exclude && exclude.includes(v.voter)) continue
    if (v.prefer === a) wa += v.weight; else wb += v.weight
    const p = Math.min(1 - CLIP, Math.max(0.5, v.p_prefer))
    const pa = v.prefer === a ? p : 1 - p
    la += v.weight * Math.log(pa)
    lb += v.weight * Math.log(1 - pa)
    lw += v.weight
  }
  const W = wa + wb
  if (!W) return { winner: null, tie: [a, b], votes: { [a]: 0, [b]: 0 }, margin: 0 }
  if (method === 'logpool') {
    const ea = Math.exp(la / lw)
    const eb = Math.exp(lb / lw)
    const qa = ea / (ea + eb)
    const qb = 1 - qa
    const w = Math.abs(qa - qb) < 1e-9 ? null : (qa > qb ? a : b)
    return { winner: w, tie: w ? [] : [a, b], votes: { [a]: round4(wa), [b]: round4(wb) }, pooled: { [a]: round4(qa), [b]: round4(qb) }, margin: round4(Math.abs(qa - qb)) }
  }
  const w = Math.abs(wa - wb) < 1e-9 ? null : (wa > wb ? a : b)
  return { winner: w, tie: w ? [] : [a, b], votes: { [a]: round4(wa), [b]: round4(wb) }, margin: round4(Math.abs(wa - wb) / W) }
}

// ---------------------------------------------------------------------------- args
const USAGE = 'Main thread only: call the Workflow tool with name "mediate" and args {problem, criteria?, method?: schulze|borda|plurality|approval|logpool, voters?: [{agentType, model? and effort? (general-purpose only; model opus|sonnet|haiku), perspective?, weight?}]}. Declare the method now: it cannot change after solutions exist.'
const parsed = parseArgs(args)
if (!parsed.ok) return { started: false, reason: parsed.error, next: USAGE }
const A = parsed.value
let problem = A.problem !== undefined ? A.problem : (A.question !== undefined ? A.question : A.task)
if (problem && typeof problem === 'object') problem = JSON.stringify(problem, null, 2)
problem = typeof problem === 'string' ? problem.trim() : ''
if (!problem) return { started: false, reason: 'missing problem (the decision to mediate, with options or constraints if known)', next: USAGE }

const criteria = Array.isArray(A.criteria) ? list(A.criteria).map((c, i) => (i + 1) + '. ' + c).join('\n') : (typeof A.criteria === 'string' && A.criteria.trim() ? A.criteria.trim() : '')
if (!criteria) log('no criteria given; voters use the default ordering (correctness, robustness, simplicity/cost). Pass criteria when voters could optimise different things.')
const criteriaText = criteria || DEFAULT_CRITERIA

const rawMethod = typeof A.method === 'string' ? A.method.trim().toLowerCase() : 'schulze'
const method = METHOD_ALIASES[rawMethod] || rawMethod
if (!METHODS.includes(method)) return { started: false, reason: 'unknown method "' + A.method + '"; valid: ' + METHODS.join(', '), next: USAGE }

let nearTie = NEAR_TIE[method]
if (A.nearTie !== undefined) {
  const x = Number(A.nearTie)
  if (Number.isFinite(x) && x >= 0 && x < 1) nearTie = x
  else log('nearTie=' + A.nearTie + ' ignored (needs a number in [0, 1)); using ' + nearTie)
}
const debateOn = A.debate !== false

let voterSpecs = A.voters
if (typeof voterSpecs === 'string') { try { voterSpecs = JSON.parse(voterSpecs) } catch (e) { return { started: false, reason: 'voters is a string but not valid JSON', next: USAGE } } }
if (voterSpecs === undefined || voterSpecs === null) voterSpecs = DEFAULT_VOTERS
if (!Array.isArray(voterSpecs)) return { started: false, reason: 'voters must be an array', next: USAGE }
const voters = []
voterSpecs.forEach((v, i) => {
  const spec = typeof v === 'string' ? { agentType: v } : v
  if (!spec || typeof spec !== 'object' || typeof spec.agentType !== 'string' || !spec.agentType.trim()) { log('voter #' + (i + 1) + ' dropped: no agentType'); return }
  // Tiers are authoritative: stack agents run on their tier and learned effort; only general-purpose takes overrides.
  const GP = spec.agentType.trim() === 'general-purpose'
  const mdl = typeof spec.model === 'string' ? spec.model.trim().toLowerCase() : ''
  if (!GP && (spec.model || spec.effort)) log('voter #' + (i + 1) + ' (' + spec.agentType + '): model/effort ignored, stack agents run on their tier')
  else if (mdl && !MODELS.includes(mdl)) log('voter #' + (i + 1) + ' model "' + spec.model + '" ignored: general-purpose takes only ' + MODELS.join('|'))
  let eff = GP && typeof spec.effort === 'string' ? spec.effort.trim().toLowerCase() : undefined
  if (eff && !EFFORTS.includes(eff)) { log('voter #' + (i + 1) + ' effort "' + eff + '" ignored'); eff = undefined }
  const w = spec.weight === undefined ? 1 : Number(spec.weight)
  voters.push({
    agentType: spec.agentType.trim(),
    model: GP && MODELS.includes(mdl) ? mdl : undefined,
    effort: eff,
    perspective: typeof spec.perspective === 'string' && spec.perspective.trim() ? spec.perspective.trim() : 'Independent generalist: solve it the way you would defend it in a design review.',
    weight: Number.isFinite(w) && w >= 0 ? w : 1,
  })
})
if (voters.length > MAX_VOTERS) { log('voters capped at ' + MAX_VOTERS + '; dropped: ' + voters.slice(MAX_VOTERS).map(v => v.agentType).join(', ')); voters.splice(MAX_VOTERS) }
if (voters.length < MIN_VOTERS) return { started: false, reason: 'need at least ' + MIN_VOTERS + ' voters, got ' + voters.length, next: USAGE }
if (!voters.some(v => v.weight > 0)) return { started: false, reason: 'all voter weights are 0', next: USAGE }
voters.forEach((v, i) => { v.id = 'V' + (i + 1) })
const distinct = new Set(voters.map(v => v.agentType + '/' + (v.model || '') + '/' + (v.effort || ''))).size
if (distinct < voters.length) log('diversity warning: ' + (voters.length - distinct) + ' voter(s) share agent/model/effort with another; correlated voters inflate apparent agreement')
const runTag = typeof A.runTag === 'string' && A.runTag.trim() ? '-' + A.runTag.trim().replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 24) : ''
const outDir = (typeof A.outDir === 'string' && A.outDir.trim() ? A.outDir.trim() : '.stack/out/mediate/' + slugify(problem) + runTag).replace(/\/+$/, '')
log('mediate: ' + voters.length + ' voters, rule ' + method + ' (declared before solving), near-tie < ' + nearTie + ', debate ' + (debateOn ? 'on' : 'off') + ', run dir ' + outDir)

// ---------------------------------------------------------------------------- Solve
const SOLUTION_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: 'the answer in at most 25 words' },
    answer: { type: 'string', description: 'self-contained solution someone could act on' },
    key_arguments: { type: 'array', items: { type: 'string' } },
    assumptions: { type: 'array', items: { type: 'string' } },
    failure_modes: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'number', minimum: 0, maximum: 1 },
  },
  required: ['summary', 'answer', 'key_arguments', 'assumptions', 'failure_modes', 'confidence'],
}
function solvePrompt(v) {
  return [
    'You are one of ' + voters.length + ' independent solvers in a blind mediated decision. Solve the problem on your own; the answers will be anonymised and ranked by all solvers.',
    '',
    'PROBLEM:',
    problem,
    '',
    'DECISION CRITERIA (priority order):',
    criteriaText,
    '',
    'YOUR LENS: ' + v.perspective + ' Use it to catch what others will miss, but answer the whole problem.',
    '',
    'RULES:',
    '- Independence: do not spawn subagents and do not look for other solvers\' answers. You may Read files the problem names and check facts (WebSearch, context7, a quick computation) when a claim decides the answer.',
    '- Self-contained answer: a reader who sees only your answer must be able to act on it. No preamble, no mention of your role, agent type or model (identifying text is stripped anyway).',
    '- If part of the problem is checkable (a test, a derivation, a measurement, a source), check it and put the result in key_arguments.',
    '- failure_modes: the concrete conditions under which your answer is wrong or breaks.',
    '- confidence: calibrated probability that your answer is the best of the reasonable alternatives (0.5 = coin flip).',
  ].join('\n')
}
phase('Solve')
const solveRes = await parallel(voters.map(v => () => call(solvePrompt(v), {
  label: 'solve ' + v.id + ' ' + v.agentType, phase: 'Solve', schema: SOLUTION_SCHEMA, agentType: v.agentType, model: v.model, effort: v.effort,
})))
const rawSolutions = []
solveRes.forEach((r, i) => {
  const v = voters[i]
  const s = r && r.value
  if (!s || typeof s !== 'object' || isBlank(s.answer)) { log('solve ' + v.id + ' (' + v.agentType + ') failed: ' + (r ? r.error || 'empty answer' : 'threw') + '; this voter still votes'); return }
  rawSolutions.push({ voter: v.id, vi: i, s })
})
if (rawSolutions.length < 2) {
  return { started: true, outDir, method, winner: null, ranking: [], tally: null, margin: null, dissent: null, final: null, reason: 'fewer than 2 solutions came back (' + rawSolutions.length + '); nothing to vote on', voters: voters.map(v => ({ id: v.id, agentType: v.agentType, model: v.model || null, effort: v.effort || null })) }
}

// ---------------------------------------------------------------------------- anonymise + label (deterministic, author-independent)
const contextText = (problem + '\n' + criteriaText).toLowerCase()
const inContext = t => new RegExp('(^|[^a-z0-9-])' + escapeRe(t.toLowerCase()) + '($|[^a-z0-9-])').test(contextText)
const agentTerms = [...new Set(STACK_AGENTS.concat(voters.map(v => v.agentType).filter(t => t.includes('-'))))].filter(t => !COMMON_AGENT_TERMS.includes(t) && !inContext(t)).sort((a, b) => b.length - a.length)
const commonTerms = COMMON_AGENT_TERMS.filter(t => !inContext(t))
const commonRe = commonTerms.length ? new RegExp('\\b(?:' + commonTerms.map(escapeRe).join('|') + ')[\\s-]+(?:sub)?agents?\\b', 'gi') : null
const modelTerms = MODEL_WORDS.filter(t => !inContext(t))
const agentRe = agentTerms.length ? new RegExp('\\b(?:' + agentTerms.map(escapeRe).join('|') + ')\\b', 'gi') : null
const modelRe = modelTerms.length ? new RegExp('\\b(?:' + modelTerms.map(escapeRe).join('|') + ')(?:[\\s-]*\\d+(?:\\.\\d+)*)?\\b', 'gi') : null
let redactions = 0
function scrub(t) {
  let x = String(t == null ? '' : t)
  const before = x
  x = x.replace(ROLE_RE, '')
  if (agentRe) x = x.replace(agentRe, '[agent]')
  if (commonRe) x = x.replace(commonRe, '[agent]')
  if (modelRe) x = x.replace(modelRe, '[model]')
  if (x !== before) redactions++
  return x
}
const anon = rawSolutions.map(r => {
  const a = {
    voter: r.voter, vi: r.vi,
    summary: scrub(r.s.summary), answer: scrub(r.s.answer),
    key_arguments: list(r.s.key_arguments).map(scrub), assumptions: list(r.s.assumptions).map(scrub), failure_modes: list(r.s.failure_modes).map(scrub),
    confidence: Number.isFinite(Number(r.s.confidence)) ? Math.min(1, Math.max(0, Number(r.s.confidence))) : null,
  }
  a.hash = fnv1a((a.answer + '\n' + a.key_arguments.join('\n')).toLowerCase().replace(/\s+/g, ' ').trim())
  return a
}).sort((x, y) => cmp(x.hash, y.hash) || (x.vi - y.vi))
anon.forEach((a, i) => { a.label = 'S' + (i + 1) })
if (redactions) log('anonymiser rewrote ' + redactions + ' field(s) containing role phrases, agent names or model names')
const dupHashes = anon.filter((a, i) => i > 0 && a.hash === anon[i - 1].hash).map(a => a.label)
if (dupHashes.length) log('identical solutions detected (' + dupHashes.join(', ') + '); clones split first-preference votes under plurality and inflate Borda')
const cands = anon.map(a => a.label)
const byLabel = {}
anon.forEach(a => { byLabel[a.label] = a })
const authorOf = {}
anon.forEach(a => { authorOf[a.voter] = a.label })
const truncated = []
function renderSolution(a) {
  if (a.answer.length > ANSWER_CAP && !truncated.includes(a.label)) truncated.push(a.label)
  return [
    '### ' + a.label,
    'Summary: ' + a.summary,
    'Answer:',
    clip(a.answer, ANSWER_CAP),
    'Key arguments:',
    bullets(a.key_arguments),
    'Assumptions:',
    bullets(a.assumptions),
    'Known failure modes:',
    bullets(a.failure_modes),
  ].join('\n')
}

// ---------------------------------------------------------------------------- Critique+Rank
function ballotSchema(labels) {
  return {
    type: 'object',
    properties: {
      ranking: { type: 'array', items: { type: 'string', enum: labels }, description: 'every label exactly once, best first' },
      approvals: { type: 'array', items: { type: 'string', enum: labels } },
      probabilities: { type: 'array', items: { type: 'object', properties: { label: { type: 'string', enum: labels }, p: { type: 'number', minimum: 0, maximum: 1 } }, required: ['label', 'p'] } },
      critiques: { type: 'array', items: { type: 'object', properties: { label: { type: 'string', enum: labels }, strength: { type: 'string' }, flaw: { type: 'string' } }, required: ['label', 'strength', 'flaw'] } },
      rationale: { type: 'string' },
    },
    required: ['ranking', 'approvals', 'probabilities', 'critiques', 'rationale'],
  }
}
const BALLOT_SCHEMA = ballotSchema(cands)
function critiquePrompt(v, vi) {
  const rot = cands.map((_, j) => cands[(j + vi) % cands.length])   // rotate order per voter to spread position bias
  return [
    'Blind review. ' + cands.length + ' anonymised solutions to the same problem follow, labelled ' + cands.join(', ') + '. One of them may be yours; do not try to identify authors. Judge only against the criteria.',
    '',
    'PROBLEM:',
    problem,
    '',
    'DECISION CRITERIA (priority order):',
    criteriaText,
    '',
    'SOLUTIONS (presentation order differs between reviewers and means nothing):',
    rot.map(l => renderSolution(byLabel[l])).join('\n\n'),
    '',
    'RETURN:',
    '- ranking: ALL ' + cands.length + ' labels, best first, each exactly once, no ties.',
    '- approvals: every label you would accept shipping as is (may be empty, may be all).',
    '- probabilities: for each label, the probability that it is the best answer; they must sum to 1 across all labels.',
    '- critiques: for EACH label its strongest point and its most serious flaw, concretely (a counterexample, a failing scenario, a violated constraint, a missing cost).',
    '- rationale: 2-4 sentences on what separated your top two.',
    'Do not spawn subagents. When a factual or mathematical claim decides your ranking, check it yourself.',
  ].join('\n')
}
phase('Critique+Rank')
const ballotRes = await parallel(voters.map((v, vi) => () => call(critiquePrompt(v, vi), {
  label: 'rank ' + v.id + ' ' + v.agentType, phase: 'Critique+Rank', schema: BALLOT_SCHEMA, agentType: v.agentType, model: v.model, effort: v.effort,
})))
if (truncated.length) log('answers truncated at ' + ANSWER_CAP + ' chars for voters: ' + truncated.join(', '))

const ballotIssues = []
const ballots = []
const critiques = {}   // label -> [{voter, strength, flaw}]
cands.forEach(c => { critiques[c] = [] })
ballotRes.forEach((r, i) => {
  const v = voters[i]
  const raw = r && r.value
  if (!raw || typeof raw !== 'object') { ballotIssues.push({ voter: v.id, issue: 'no ballot (' + (r ? r.error : 'threw') + '); excluded' }); return }
  if (v.weight === 0) ballotIssues.push({ voter: v.id, issue: 'weight 0: ballot recorded but has no effect' })
  const norm = l => { const m = /S\s*(\d+)/i.exec(String(l)); return m ? 'S' + parseInt(m[1], 10) : String(l).trim() }
  const seen = new Set()
  const ranking = []
  for (const l of list(raw.ranking).map(norm)) {
    if (!cands.includes(l)) { ballotIssues.push({ voter: v.id, issue: 'unknown label ' + l + ' dropped' }); continue }
    if (seen.has(l)) { ballotIssues.push({ voter: v.id, issue: 'duplicate ' + l + ' ignored' }); continue }
    seen.add(l)
    ranking.push(l)
  }
  const unranked = cands.filter(c => !seen.has(c))
  if (unranked.length) ballotIssues.push({ voter: v.id, issue: 'unranked ' + unranked.join(', ') + ' treated as tied last (not imputed)' })
  const tiers = ranking.map(l => [l])
  if (unranked.length) tiers.push(unranked)
  const approvals = [...new Set(list(raw.approvals).map(norm).filter(l => cands.includes(l)))]
  let p = {}
  let psum = 0
  for (const e of Array.isArray(raw.probabilities) ? raw.probabilities : []) {
    const l = norm(e && e.label)
    const x = Number(e && e.p)
    if (cands.includes(l) && Number.isFinite(x) && x >= 0) { p[l] = (p[l] || 0) + x; psum += x }
  }
  const pMissing = cands.filter(c => !(c in p))
  if (psum <= 0) { ballotIssues.push({ voter: v.id, issue: 'no usable probabilities; excluded from the log pool' }); p = null }
  else {
    if (pMissing.length) ballotIssues.push({ voter: v.id, issue: 'no probability for ' + pMissing.join(', ') + '; set to 0 (clipped to ' + CLIP + ')' })
    if (Math.abs(psum - 1) > 0.05) ballotIssues.push({ voter: v.id, issue: 'probabilities summed to ' + round4(psum) + '; renormalised' })
    cands.forEach(c => { p[c] = (p[c] || 0) / psum })
  }
  for (const c of Array.isArray(raw.critiques) ? raw.critiques : []) {
    const l = norm(c && c.label)
    if (cands.includes(l)) critiques[l].push({ voter: v.id, strength: String(c.strength || ''), flaw: String(c.flaw || '') })
  }
  ballots.push({ voter: v.id, weight: v.weight, tiers, ranking, approvals, p, author_of: authorOf[v.id] || null, rationale: String(raw.rationale || '') })
})
ballotIssues.forEach(b => log('ballot ' + b.voter + ': ' + b.issue))
if (ballots.length < 2) {
  return { started: true, outDir, method, winner: null, ranking: [], tally: null, margin: null, dissent: null, final: null, ballot_issues: ballotIssues, reason: 'fewer than 2 ballots came back; no vote possible' }
}

// ---------------------------------------------------------------------------- Tally
phase('Tally')
const declared = run(ballots, cands, method, false)
const allMethods = {}
const skippedMethods = []
for (const m of METHODS) {
  if (m === 'logpool' && !ballots.some(b => b.p)) { skippedMethods.push('logpool: no probabilities in any ballot'); continue }
  if (m === 'approval' && !ballots.some(b => b.approvals.length)) { skippedMethods.push('approval: no approvals in any ballot'); continue }
  const r = m === method ? declared : run(ballots, cands, m, false)
  allMethods[m] = { winner: r.winner, tie: r.tie, runner_up: r.runner_up, margin: r.margin, scores: r.scores }
}
const noSelf = run(ballots, cands, method, true)
const loo = ballots.map((b, i) => {
  const sub = ballots.filter((_, j) => j !== i)
  const r = run(sub, cands, method, false)
  return { dropped: b.voter, winner: r.winner, tie: r.tie }
})
const looStability = round4(loo.filter(r => declared.winner && r.winner === declared.winner).length / loo.length)
const selfRank = ballots.filter(b => b.author_of).map(b => ({ voter: b.voter, own: b.author_of, own_position: b.ranking.indexOf(b.author_of) + 1 || null, of: cands.length }))
const methodWinners = {}
Object.keys(allMethods).forEach(m => { methodWinners[m] = allMethods[m].winner })
const methodSensitive = new Set(Object.values(methodWinners)).size > 1
const robustness = {
  no_self_winner: noSelf.winner, no_self_tie: noSelf.tie, no_self_margin: noSelf.margin,
  leave_one_out: loo, loo_stability: looStability, self_rank: selfRank,
  method_agreement: methodWinners, method_sensitive: methodSensitive, skipped_methods: skippedMethods,
}
const nearReasons = []
if (!declared.winner) nearReasons.push('tie between ' + declared.tie.join(', '))
else if (declared.margin < nearTie) nearReasons.push('margin ' + declared.margin + ' < ' + nearTie)
if (declared.winner && noSelf.winner !== declared.winner) nearReasons.push('winner changes to ' + (noSelf.winner || 'a tie') + ' when voters\' own solutions are excluded')
if (method === 'schulze' && !declared.condorcet_winner) nearReasons.push('no Condorcet winner (pairwise cycle)')
if (declared.winner && declared.pairwise_margin !== undefined && declared.pairwise_margin < nearTie) nearReasons.push('direct pairwise margin ' + declared.pairwise_margin + ' < ' + nearTie)
if (declared.winner && looStability < 1) nearReasons.push('leave-one-out stability ' + looStability + ' < 1 (dropping one voter changes the winner)')
const isNearTie = nearReasons.length > 0
log('tally ' + method + ': ' + (declared.winner ? 'winner ' + declared.winner : 'tie ' + declared.tie.join('/')) + ', runner-up ' + declared.runner_up + ', margin ' + declared.margin +
  '; no-self ' + (noSelf.winner || 'tie') + '; LOO stability ' + looStability + (methodSensitive ? '; METHOD-SENSITIVE ' + JSON.stringify(methodWinners) : '') + (isNearTie ? '; NEAR-TIE: ' + nearReasons.join('; ') : ''))

// ---------------------------------------------------------------------------- Debate (near-tie only)
let debate = null
let winner = declared.winner
let tie = declared.tie.slice()
let decidedBy = 'declared rule'
if (isNearTie) {
  let top2
  if (declared.tie.length >= 2) {
    const bordaScores = borda(ballots, cands, false)
    top2 = declared.tie.slice().sort((a, b) => (bordaScores[b] - bordaScores[a]) || (labelNum(a) - labelNum(b))).slice(0, 2)
    if (declared.tie.length > 2) log('tie among ' + declared.tie.length + '; debate between the top two by Borda (' + top2.join(', ') + '), excluded: ' + declared.tie.filter(l => !top2.includes(l)).join(', '))
  } else {
    top2 = [declared.winner, declared.runner_up]
  }
  const authors = top2.map(l => voters.find(v => v.id === byLabel[l].voter))
  const skipReason = !debateOn ? 'debate disabled by args' : (budget.total && budget.remaining() < DEBATE_MIN_BUDGET ? 'token budget below ' + DEBATE_MIN_BUDGET : (!top2[1] ? 'no runner-up' : null))
  if (skipReason) {
    log('near-tie but debate skipped: ' + skipReason)
    debate = { ran: false, reason: skipReason, between: top2 }
    decidedBy = winner ? 'declared rule (near-tie, no debate)' : 'unresolved tie'
  } else {
    phase('Debate')
    const REBUTTAL_SCHEMA = {
      type: 'object',
      properties: { rebuttal: { type: 'string', description: 'at most 300 words' }, concessions: { type: 'array', items: { type: 'string' } }, decisive_criterion: { type: 'string' } },
      required: ['rebuttal', 'concessions', 'decisive_criterion'],
    }
    const critBlock = l => critiques[l].map(c => '- strength: ' + c.strength + '\n  flaw: ' + c.flaw).join('\n') || '- (none)'
    const rebuttals = await parallel(top2.map((l, k) => () => {
      const other = top2[1 - k]
      return call([
        'Debate round of a blind mediated decision. You wrote solution ' + l + '. It finished in a near-tie with ' + other + ' (' + nearReasons.join('; ') + ').',
        '',
        'PROBLEM:', problem, '', 'DECISION CRITERIA:', criteriaText, '',
        renderSolution(byLabel[l]), '', 'Critiques of ' + l + ' from the voters:', critBlock(l), '',
        renderSolution(byLabel[other]), '', 'Critiques of ' + other + ' from the voters:', critBlock(other), '',
        'Write a rebuttal of at most 300 words: answer the most serious flaw raised against ' + l + ', state the most serious flaw in ' + other + ', concede what is right, and name the single criterion that should decide between them.',
        'Refer to solutions only by label. Do not reveal your role, agent type or model. Do not spawn subagents.',
      ].join('\n'), { label: 'rebut ' + l + ' (' + authors[k].id + ')', phase: 'Debate', schema: REBUTTAL_SCHEMA, agentType: authors[k].agentType, model: authors[k].model, effort: authors[k].effort })
    }))
    const reb = rebuttals.map((r, k) => (r && r.value && typeof r.value === 'object') ? { label: top2[k], rebuttal: scrub(r.value.rebuttal), concessions: list(r.value.concessions).map(scrub), decisive_criterion: scrub(r.value.decisive_criterion) } : { label: top2[k], rebuttal: '(no rebuttal: ' + (r ? r.error : 'threw') + ')', concessions: [], decisive_criterion: '' })
    const REVOTE_SCHEMA = {
      type: 'object',
      properties: { prefer: { type: 'string', enum: top2 }, p_prefer: { type: 'number', minimum: 0.5, maximum: 1 }, reason: { type: 'string' } },
      required: ['prefer', 'p_prefer', 'reason'],
    }
    const voting = voters.filter(v => ballots.some(b => b.voter === v.id))
    const revotes = await parallel(voting.map(v => () => call([
      'Pairwise re-vote after a debate round in a blind mediated decision. Choose between ' + top2[0] + ' and ' + top2[1] + ' against the criteria.',
      '', 'PROBLEM:', problem, '', 'DECISION CRITERIA:', criteriaText, '',
      renderSolution(byLabel[top2[0]]), '', renderSolution(byLabel[top2[1]]), '',
      reb.map(x => '### Rebuttal for ' + x.label + '\n' + x.rebuttal + '\nConcedes:\n' + bullets(x.concessions) + '\nDecisive criterion proposed: ' + (x.decisive_criterion || '-')).join('\n\n'), '',
      'Return prefer (one label), p_prefer (probability in [0.5, 1] that your choice is the better one) and a reason of at most 3 sentences naming the deciding consideration. Do not spawn subagents.',
    ].join('\n'), { label: 'revote ' + v.id + ' ' + v.agentType, phase: 'Debate', schema: REVOTE_SCHEMA, agentType: v.agentType, model: v.model, effort: v.effort })))
    const votes = []
    revotes.forEach((r, i) => {
      const v = voting[i]
      const x = r && r.value
      if (!x || !top2.includes(x.prefer)) { ballotIssues.push({ voter: v.id, issue: 're-vote missing or invalid; excluded from the debate tally' }); return }
      votes.push({ voter: v.id, weight: v.weight, prefer: x.prefer, p_prefer: Number.isFinite(Number(x.p_prefer)) ? Number(x.p_prefer) : 0.5, reason: String(x.reason || '') })
    })
    const pt = pairTally(votes, top2[0], top2[1], method, null)
    const ptNoSelf = pairTally(votes, top2[0], top2[1], method, authors.map(a => a.id))
    debate = { ran: true, between: top2, authors: authors.map(a => a.id), triggers: nearReasons, rebuttals: reb, votes, result: pt, result_without_authors: ptNoSelf, still_near_tie: [] }
    if (pt.winner) {
      winner = pt.winner
      tie = []
      decidedBy = 'debate re-vote (' + top2.join(' vs ') + ', margin ' + pt.margin + ')'
      // Still a near-tie (mediator-voting section 8 step 3): narrow weighted majority or one voter flips it.
      const wsum = pt.votes[top2[0]] + pt.votes[top2[1]]
      const voteMargin = wsum ? round4(Math.abs(pt.votes[top2[0]] - pt.votes[top2[1]]) / wsum) : 0
      if (voteMargin < REVOTE_NEAR_TIE) debate.still_near_tie.push('re-vote majority margin ' + voteMargin + ' < ' + REVOTE_NEAR_TIE)
      if (votes.some((_, i) => pairTally(votes.filter((_, j) => j !== i), top2[0], top2[1], method, null).winner !== pt.winner)) debate.still_near_tie.push('dropping one re-vote flips the winner')
      if (debate.still_near_tie.length) {
        debate.pooled_p = pairTally(votes, top2[0], top2[1], 'logpool', null).pooled
        decidedBy += '; STILL NEAR-TIE (' + debate.still_near_tie.join('; ') + '): provisional, tie-break cascade left to synthesis'
      }
    } else {
      winner = null
      tie = top2.slice()
      decidedBy = 'declared tie after debate'
    }
    log('debate: ' + (pt.winner ? pt.winner + ' wins ' + JSON.stringify(pt.votes) : 'still tied ' + JSON.stringify(pt.votes)) + (ptNoSelf.winner !== pt.winner ? '; without the two authors: ' + (ptNoSelf.winner || 'tie') : ''))
  }
}

// Final ranking: declared tiers, with the debate outcome applied to the top two.
let finalRanking = declared.ranking.map(t => t.slice())
if (debate && debate.ran && winner) {
  const loser = debate.between.find(l => l !== winner)
  const rest = finalRanking.map(t => t.filter(l => !debate.between.includes(l))).filter(t => t.length)
  finalRanking = [[winner], [loser]].concat(rest)
}

// ---------------------------------------------------------------------------- dissent (code)
const n = cands.length
const firsts = {}
ballots.forEach(b => { const f = b.tiers[0]; if (f && f.length === 1) firsts[f[0]] = (firsts[f[0]] || 0) + 1 })
const dissent = {
  winner_ranked_last: winner && n > 2 ? ballots.filter(b => b.tiers[b.tiers.length - 1].includes(winner)).map(b => ({ voter: b.voter, flaw: (critiques[winner].find(c => c.voter === b.voter) || {}).flaw || '' })) : [],
  low_probability_on_winner: winner ? ballots.filter(b => b.p && b.p[winner] < 1 / n).map(b => ({ voter: b.voter, p: round4(b.p[winner]) })) : [],
  minority_first_choices: cands.filter(l => l !== winner && firsts[l]).map(l => ({ label: l, first_place_votes: firsts[l], author: byLabel[l].voter, strengths: critiques[l].map(c => c.strength).filter(Boolean).slice(0, 3) })),
}

// ---------------------------------------------------------------------------- Synthesize
const SYNTH_SCHEMA = {
  type: 'object',
  properties: {
    final: { type: 'string', description: 'the complete final answer' },
    grafts: { type: 'array', items: { type: 'object', properties: { from: { type: 'string' }, idea: { type: 'string' }, why_compatible: { type: 'string' } }, required: ['from', 'idea', 'why_compatible'] } },
    rejected_grafts: { type: 'array', items: { type: 'string' } },
    dissent_note: { type: 'string' },
    verification_needed: { type: 'array', items: { type: 'string' } },
    tally_check: { type: 'string' },
    report_path: { type: 'string' },
    confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
  },
  required: ['final', 'grafts', 'rejected_grafts', 'dissent_note', 'verification_needed', 'tally_check', 'report_path', 'confidence'],
}
const tallyInput = {
  candidates: cands,
  exclusive: true,
  ballots: ballots.map(b => ({ voter: b.voter, ranking: b.tiers.map(t => (t.length === 1 ? t[0] : t)), approvals: b.approvals, p_correct: b.p || {}, weight: b.weight, author_of: b.author_of || undefined })),
}
const focus = winner ? [winner].concat(finalRanking.flat().filter(l => l !== winner).slice(0, 2)) : tie.concat(finalRanking.flat().filter(l => !tie.includes(l)).slice(0, 1))
const others = cands.filter(l => !focus.includes(l))
const voteTable = ballots.map(b => '| ' + b.voter + ' | ' + b.tiers.map(t => t.join('=')).join(' > ') + ' | ' + (b.approvals.join(', ') || '-') + ' | ' + (b.p ? cands.map(c => c + ':' + round4(b.p[c])).join(' ') : '-') + ' |').join('\n')
const synthPrompt = [
  'SYNTHESIS MODE for the mediate workflow. Voting is finished and the rule was declared before solving: do not re-vote, do not change the winner, do not spawn.',
  '',
  'PROBLEM:', problem, '', 'DECISION CRITERIA:', criteriaText, '',
  'RULE: ' + method + ' (near-tie threshold ' + nearTie + '). OUTCOME: ' + (winner ? 'winner ' + winner : 'declared tie between ' + tie.join(' and ')) + ', decided by ' + decidedBy + '.',
  'Declared tally: ranking ' + declared.ranking.map(t => t.join('=')).join(' > ') + '; margin ' + declared.margin + '; scores ' + JSON.stringify(declared.scores) + (declared.condorcet_winner !== undefined ? '; Condorcet winner ' + (declared.condorcet_winner || 'none') : ''),
  'Other rules: ' + JSON.stringify(methodWinners) + (methodSensitive ? ' (METHOD-SENSITIVE)' : '') + '. No-self winner: ' + (noSelf.winner || 'tie ' + noSelf.tie.join('/')) + '. Leave-one-out stability: ' + looStability + '.',
  isNearTie ? 'Near-tie triggers: ' + nearReasons.join('; ') : 'Not a near-tie.',
  debate && debate.ran ? 'Debate: ' + JSON.stringify({ between: debate.between, result: debate.result, without_authors: debate.result_without_authors, decisive_criteria: debate.rebuttals.map(r => r.label + ': ' + r.decisive_criterion) }) : (debate ? 'Debate not run: ' + debate.reason : ''),
  debate && debate.ran && debate.still_near_tie.length ? 'STILL A NEAR-TIE after the debate (' + debate.still_near_tie.join('; ') + '); ' + winner + ' is provisional. Tie-break cascade, first rule that separates them: (1) verifiable evidence you can run yourself on both (test, recomputation, source); (2) pooled p over the re-vote ballots ' + JSON.stringify(debate.pooled_p) + '; (3) fewer unresolved checkable objections; (4) cheaper to reverse. Do not change the winner yourself: report what the cascade shows in dissent_note, put both candidates and the crux in verification_needed (an Open doubt for the caller), and set confidence low.' : '',
  '',
  'VOTE TABLE (voter | ranking | approvals | P(best)):',
  voteTable,
  '',
  'SOLUTIONS IN FOCUS (winner first, then the strongest runners-up):',
  focus.map(l => renderSolution(byLabel[l]) + '\nVoter critiques:\n' + (critiques[l].map(c => '- [' + c.voter + '] + ' + c.strength + ' / - ' + c.flaw).join('\n') || '- (none)')).join('\n\n'),
  '',
  others.length ? 'OTHER SOLUTIONS (summaries; graft candidates only if critiques rated the idea a strength):\n' + others.map(l => '- ' + l + ': ' + byLabel[l].summary + ' | strengths: ' + critiques[l].map(c => c.strength).filter(Boolean).slice(0, 3).join(' / ')).join('\n') : '',
  '',
  'DISSENT (computed in code): ' + JSON.stringify(dissent),
  'AUTHOR MAP (revealed only now, for the dissent report): ' + JSON.stringify(anon.map(a => ({ label: a.label, voter: a.voter, agentType: voters[a.vi].agentType, model: voters[a.vi].model || 'default' }))),
  '',
  'DO:',
  '1. Save this JSON to ' + outDir + '/ballots.json and run: T=.claude/skills/mediator-voting/scripts/tally.py; [ -f "$T" ] || T="$HOME/.claude/stack/.claude/skills/mediator-voting/scripts/tally.py"; python3 "$T" ' + outDir + '/ballots.json --method ' + method,
  '   If neither path exists, start tally_check with "unavailable:" and say so; that is not a discrepancy.',
  '   Compare its winner, runner-up and margin with the declared tally above (the debate outcome is not in tally.py). Put "match" or the exact discrepancy in tally_check; a discrepancy is reported, never acted on.',
  '   For schulze both use the unbeaten-tier winner set and the strongest-path margin (p[w][r] - p[r][w]) / W; pairwise_margin (direct counts) is an extra near-tie trigger of this workflow, not a discrepancy.',
  '   ' + JSON.stringify(tallyInput),
  '2. ' + (winner ? 'Write the final answer with ' + winner + ' as the base. Graft a runner-up idea only when voters rated it a strength AND it does not contradict the winner\'s core assumptions; cite each graft by label. Never average incompatible solutions into a compromise nobody proposed.' : 'Declared tie: present both ' + tie.join(' and ') + ' faithfully, name the criterion that separates them and what evidence would decide it; do not pick one.'),
  '3. List checkable key claims of the final answer in verification_needed (the caller routes them to adversarial-verifier or tester).',
  '4. Write ' + outDir + '/report.md: frame (problem, criteria, rule declared before solving), solution summaries, vote table, tally and robustness numbers, debate, final answer, grafts with labels, dissent (with the strongest minority argument), open doubts. Return its path in report_path.',
  '5. confidence: high only if the margin is above the threshold, leave-one-out stability is 1, the winner is stable across rules and under no-self, and no unresolved critique breaks it; a narrow, voter-fragile or rule-dependent win is at most medium; still a near-tie after the debate is low.',
].filter(x => x !== '').join('\n')
phase('Synthesize')
const syn = await call(synthPrompt, { label: 'synthesize ' + (winner || 'tie ' + tie.join('/')), phase: 'Synthesize', agentType: 'mediator', schema: SYNTH_SCHEMA })
let synthesis = null
let final = null
if (syn.value && typeof syn.value === 'object') { synthesis = syn.value; final = syn.value.final }
else {
  log('synthesis failed (' + syn.error + '); returning the winning solution unmodified')
  final = winner ? byLabel[winner].answer : tie.map(l => '## ' + l + '\n' + byLabel[l].answer).join('\n\n')
}
if (synthesis && synthesis.tally_check && !/^\s*(match|unavailable)/i.test(synthesis.tally_check)) log('TALLY CHECK DISCREPANCY reported by mediator: ' + synthesis.tally_check)

return {
  started: true,
  outDir,
  method,
  winner,
  tie,
  decided_by: decidedBy,
  winner_author: winner ? { voter: byLabel[winner].voter, agentType: voters[byLabel[winner].vi].agentType } : null,
  ranking: finalRanking,
  margin: debate && debate.ran && debate.result ? debate.result.margin : declared.margin,
  near_tie: isNearTie,
  near_tie_reasons: nearReasons,
  tally: { declared, all_methods: allMethods, robustness, ballots: tallyInput.ballots },
  debate,
  dissent,
  final,
  synthesis: synthesis ? { grafts: synthesis.grafts, rejected_grafts: synthesis.rejected_grafts, dissent_note: synthesis.dissent_note, verification_needed: synthesis.verification_needed, tally_check: synthesis.tally_check, report_path: synthesis.report_path, confidence: synthesis.confidence } : null,
  solutions: anon.map(a => ({ label: a.label, summary: a.summary, author: a.voter, agentType: voters[a.vi].agentType, self_confidence: a.confidence })),
  voters: voters.map(v => ({ id: v.id, agentType: v.agentType, model: v.model || null, effort: v.effort || null, weight: v.weight, perspective: v.perspective })),
  ballot_issues: ballotIssues,
}
