export const meta = {
  name: 'swarm-run',
  description: 'Swarm over shards: one worker per shard (pipelined), per-shard normalisation, one retry of the uncovered remainder, then exact-key dedup and a coverage ledger in code and a swarm-coordinator merge',
  whenToUse: 'More than 6 homogeneous shards of one job (files or packages to audit, URL batches to extract, hypotheses to test, grid chunks to run) whose results must be deduplicated and merged with provable coverage. Main thread only. args {task, shards: [string | {id, brief}], agentType?=general-purpose (prefer a tiered stack agent), model? (opus|sonnet|haiku, general-purpose only; default sonnet), effort? (general-purpose only), merge?, key?, retry?=1, maxShards?=150, outDir?, runTag?, resume?=false}',
  phases: [
    { title: 'Work', detail: 'one worker per shard with the swarm brief template; a dead worker is re-run once; partial or failed shards get one retry over the uncovered remainder (split in two when large); XSHARD follow-ups' },
    { title: 'Normalize', detail: 'file-summarizer (LOW tier, its own learned effort) turns each worker return into a status, unit counts and keyed items record (code fallback parser when it fails)' },
    { title: 'Merge', detail: 'barrier; exact-key dedup and coverage ledger computed in code; swarm-coordinator in merge mode for semantic dedup, conflicts, merged.json and ledger.md' },
  ],
}

// ---------------------------------------------------------------------------- constants
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']
const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']
const DEFAULT_MERGE = 'Union + dedup by item key; keep the highest severity, the most specific failure scenario, the union of evidence and of contributing shards; list contradictions between shards as conflicts (never resolve them silently); state which zero-item shards are evidence of absence (status ok) and which are not.'
const DEFAULT_KEY = 'a stable identifier that is identical when two shards report the same thing: path::symbol::class for code findings, canonical URL (lower-case host, no www, no fragment, no utm_*) for sources, arXiv id without version or lower-case DOI for papers, the hypothesis id for hypotheses, the rounded parameter tuple for grid points'
const RETURN_TEXT_CAP = 24000      // chars of a worker return handed to the normaliser
const INLINE_ITEMS_CAP = 3000      // chars of deduped items inlined into the merge prompt (config/policy.json offload_chars)
const RETURN_ITEMS_CAP = 100       // deduped items carried in this workflow's return value
const DEFAULT_MAX_SHARDS = 150     // usually ~2 agents per shard (work + normalize); retries add up to 4 more
const HARD_MAX_SHARDS = 165        // worst case 6 agents per shard (work, normalize, 2 x retry worker + normalizer) + 5 XSHARD + 1 merge <= 1000-agent workflow cap
const SPLIT_MIN_UNITS = 8          // a failed shard with at least this many listed units is bisected on retry
const XSHARD_MIN_QUESTIONS = 3     // follow-up worker when this many XSHARD doubts hit one target
const XSHARD_MAX_FOLLOWUPS = 5
const RETRY_MIN_BUDGET = 40000     // tokens; below this (with a budget set) retries are skipped
const MODELS = ['opus', 'sonnet', 'haiku']   // tier aliases; only general-purpose takes a per-call model

// ---------------------------------------------------------------------------- helpers
function fnv1a(s) {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 }
  return (h >>> 0).toString(16).padStart(8, '0')
}
function slugify(s) {
  const words = String(s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean).slice(0, 6)
  return (words.join('-').slice(0, 40) || 'swarm') + '-' + fnv1a(String(s)).slice(0, 6)
}
function clip(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n) : s }
function isBlank(v) { return v === null || v === undefined || (typeof v === 'string' && !v.trim()) }
function normKey(k) { return String(k == null ? '' : k).trim().toLowerCase().replace(/\s+/g, ' ').replace(/\/+$/, '') }
function sevRank(s) { const i = SEVERITY_ORDER.indexOf(String(s || '').toLowerCase()); return i < 0 ? SEVERITY_ORDER.length : i }
function bumpEffort(e) { if (!e) return undefined; const i = EFFORTS.indexOf(e); return EFFORTS[Math.min(EFFORTS.length - 1, i + 1)] }
function toInt(v) { const n = Math.floor(Number(v)); return Number.isFinite(n) && n > 0 ? n : 0 }
async function call(prompt, opts) {
  try {
    const value = await agent(prompt, opts)
    return { value, error: isBlank(value) ? (value == null ? 'agent returned null' : 'agent returned empty text') : null }
  } catch (e) {
    return { value: null, error: 'agent threw: ' + clip(e && e.message ? e.message : e, 300) }
  }
}
function parseArgs(raw) {
  if (raw === undefined || raw === null || raw === '') return { ok: true, value: {} }
  if (typeof raw === 'string') {
    try { return { ok: true, value: JSON.parse(raw) } } catch (e) { return { ok: false, error: 'args is a string but not valid JSON: ' + e.message } }
  }
  if (typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, error: 'args must be an object' }
  return { ok: true, value: raw }
}

// ---------------------------------------------------------------------------- args
const USAGE = 'Main thread only: call the Workflow tool with name "swarm-run" and args {task, shards: [string | {id, brief}], agentType?, model? and effort? (general-purpose only), merge?, key?, runTag?}. Enumerate the universe in code (git ls-files, Glob, a URL list), shard it (swarm-execution skill; .claude/skills/swarm-execution/scripts/shard_plan.py prints ready-made shards), then launch.'
const parsed = parseArgs(args)
if (!parsed.ok) return { started: false, reason: parsed.error, next: USAGE }
const A = parsed.value
if (!A || typeof A !== 'object' || Array.isArray(A)) return { started: false, reason: 'args must be a JSON object', next: USAGE }

const task = typeof A.task === 'string' ? A.task.trim() : ''
let rawShards = A.shards
if (typeof rawShards === 'string') { try { rawShards = JSON.parse(rawShards) } catch (e) { rawShards = null } }
const missing = []
if (!task) missing.push('task (string shared by every shard: SWARM GOAL, TASK, acceptance criteria, ITEM FORMAT)')
if (!Array.isArray(rawShards) || rawShards.length === 0) missing.push('shards (non-empty array of strings or {id, brief})')
if (missing.length) return { started: false, reason: 'missing or invalid: ' + missing.join('; '), next: USAGE }

const workerType = typeof A.agentType === 'string' && A.agentType.trim() ? A.agentType.trim() : 'general-purpose'
// Tiers are authoritative: stack agents run on their tier and learned effort; only general-purpose takes overrides.
const GP = workerType === 'general-purpose'
const rawModel = typeof A.model === 'string' ? A.model.trim().toLowerCase() : ''
if (!GP && (A.model || A.effort)) log('model/effort ignored: ' + workerType + ' runs on its tier and learned effort from config/models.json (overrides apply to general-purpose only)')
else if (rawModel && !MODELS.includes(rawModel)) log('model "' + A.model + '" ignored: general-purpose takes only ' + MODELS.join('|'))
// general-purpose is untiered and would inherit the main-loop model: default its workers to the MEDIUM tier alias.
const workerModel = GP ? (MODELS.includes(rawModel) ? rawModel : 'sonnet') : undefined
if (GP && !MODELS.includes(rawModel)) log('general-purpose workers run on sonnet (MEDIUM tier); pass model, or pick a tiered stack agent as agentType')
let workerEffort = GP && typeof A.effort === 'string' ? A.effort.trim().toLowerCase() : undefined
if (workerEffort && !EFFORTS.includes(workerEffort)) { log('effort "' + workerEffort + '" is not one of ' + EFFORTS.join('/') + '; ignored, workers use their frontmatter default'); workerEffort = undefined }
const mergeSpec = typeof A.merge === 'string' && A.merge.trim() ? A.merge.trim() : DEFAULT_MERGE
const keySpec = typeof A.key === 'string' && A.key.trim() ? A.key.trim() : DEFAULT_KEY
let retry = A.retry === undefined ? 1 : toInt(A.retry)
if (A.retry === 0 || A.retry === false) retry = 0
if (retry > 1) { log('retry=' + retry + ' capped at 1: a unit gets at most two attempts (original + one retry)'); retry = 1 }
let maxShards = A.maxShards === undefined ? DEFAULT_MAX_SHARDS : toInt(A.maxShards) || DEFAULT_MAX_SHARDS
if (maxShards > HARD_MAX_SHARDS) { log('maxShards=' + maxShards + ' capped at ' + HARD_MAX_SHARDS + ' (workflow agent cap)'); maxShards = HARD_MAX_SHARDS }
const runTag = typeof A.runTag === 'string' && A.runTag.trim() ? '-' + A.runTag.trim().replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 24) : ''
const resume = A.resume === true   // reuse shard files that already say STATUS ok (same outDir, same task)
const outDir = (typeof A.outDir === 'string' && A.outDir.trim() ? A.outDir.trim() : '.stack/out/swarm-run/' + slugify(task) + runTag).replace(/\/+$/, '')
if (!runTag && !resume && !(typeof A.outDir === 'string' && A.outDir.trim())) log('run dir ' + outDir + ' is shared by every run of this task; pass runTag (e.g. a date stamp) to keep runs apart')

// ---------------------------------------------------------------------------- shards
const idWidth = Math.max(2, String(rawShards.length).length)
const seenIds = new Set()
const shards = []
const rejected = []
rawShards.forEach((s, i) => {
  let id = ''
  let brief = ''
  if (typeof s === 'string') brief = s.trim()
  else if (s && typeof s === 'object') {
    id = s.id != null ? String(s.id).trim() : ''
    const units = Array.isArray(s.units) ? s.units.map(String).join('\n') : ''
    brief = String(s.brief || s.scope || units || '').trim()
  }
  if (!brief) { rejected.push({ id: id || '#' + (i + 1), status: 'dropped', reason: 'empty brief', attempts: 0 }); return }
  if (!id) id = 's' + String(i + 1).padStart(idWidth, '0')
  id = id.replace(/[^A-Za-z0-9._-]+/g, '-')
  if (seenIds.has(id)) {
    let k = 2
    while (seenIds.has(id + '-' + k)) k++
    log('duplicate shard id "' + id + '" renamed to "' + id + '-' + k + '"')
    id = id + '-' + k
  }
  seenIds.add(id)
  shards.push({ id, brief })
})
if (rejected.length) log('dropped ' + rejected.length + ' shard(s) with an empty brief: ' + rejected.map(r => r.id).join(', '))
let capped = []
if (shards.length > maxShards) {
  capped = shards.splice(maxShards)
  log('CAPPED: ' + capped.length + ' shard(s) beyond maxShards=' + maxShards + ' were NOT run: ' + capped.map(s => s.id).join(', ') + '. Re-run them in a second Workflow name=swarm-run call.')
}
if (!shards.length) return { started: false, reason: 'no runnable shards after validation', rejected, next: USAGE }
const S = shards.length
shards.forEach((s, i) => { s.k = i + 1 })
log('swarm: ' + S + ' shard(s) x ' + workerType + (workerModel ? '/' + workerModel : '') + (workerEffort ? '/' + workerEffort : '') +
  '; planned agents ~' + (2 * S + 1) + ' plus up to ' + (4 * retry * S + XSHARD_MAX_FOLLOWUPS) + ' for retries and XSHARD follow-ups; run dir ' + outDir)

// ---------------------------------------------------------------------------- prompts and schemas
function workerPrompt(sh, scope, note) {
  return [
    'SWARM GOAL: ' + task,
    'SHARD: ' + sh.id + ' (' + sh.k + ' of ' + S + ')' + (note ? ' - ' + note : ''),
    'SCOPE:',
    scope,
    'OUT OF SCOPE: everything else. You may read outside scope only to resolve a referenced symbol or citation (at most 5 such reads; list them under Evidence).',
    'ITEM FORMAT: one entry per item, each with a dedup KEY (' + keySpec + ') plus a one-line summary, severity or priority when meaningful, location, and evidence.',
    'WRITE: full details to ' + outDir + '/shards/' + sh.id + '.md (create directories as needed). Its first line is the status line below. ' +
      (resume ? 'If that file already exists and its first line says STATUS ok, return its summary without redoing the work.' : 'Overwrite any existing file there: it is from an earlier run.'),
    'RETURN (output contract). The FIRST line of Result is exactly:',
    '  SHARD ' + sh.id + ' STATUS <ok|partial|failed> COVERED <n>/<m> ITEMS <k>',
    '  m = units in your scope, n = units you fully checked. partial = you ran out of budget: list each unchecked unit under Evidence as a line "UNCOVERED: <unit>".',
    '  Then one line per item: "ITEM <key> | <summary> | <severity> | <location>". More than 15 items, or a Result past ~60 lines / ~3k characters: list the top 15 here, put all items in the file and say so.',
    'CROSS-SHARD: if an item depends on something outside your scope, add an Open doubt "XSHARD: <question> -> <unit or path>" and do not chase it.',
    'SPAWNING: do not spawn subagents; ' + S + ' shards run concurrently and share one spawn budget. Return Open doubts instead.',
    'BUDGET: use at most about 60% of your maxTurns in tool calls (about 120 if you cannot see your maxTurns); then write the file and return, partial if needed. Zero items is a valid result; say exactly what you checked.',
  ].join('\n')
}

const ITEM_SCHEMA = {
  type: 'object',
  properties: { key: { type: 'string' }, summary: { type: 'string' }, severity: { type: 'string' }, location: { type: 'string' } },
  required: ['key', 'summary'],
}
const RECORD_SCHEMA = {
  type: 'object',
  properties: {
    shard_id: { type: 'string' },
    status: { type: 'string', enum: ['ok', 'partial', 'failed'] },
    units_total: { type: 'integer', minimum: 0 },
    units_covered: { type: 'integer', minimum: 0 },
    uncovered: { type: 'array', items: { type: 'string' } },
    items: { type: 'array', items: ITEM_SCHEMA },
    xshard: { type: 'array', items: { type: 'object', properties: { question: { type: 'string' }, target: { type: 'string' } }, required: ['question', 'target'] } },
    file: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['shard_id', 'status', 'units_total', 'units_covered', 'uncovered', 'items', 'xshard', 'file', 'notes'],
}
const MERGE_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    merged_path: { type: 'string' },
    ledger_path: { type: 'string' },
    unique_items: { type: 'integer', minimum: 0 },
    semantic_duplicates_removed: { type: 'integer', minimum: 0 },
    top_items: { type: 'array', items: { type: 'object', properties: { key: { type: 'string' }, summary: { type: 'string' }, severity: { type: 'string' }, shards: { type: 'array', items: { type: 'string' } } }, required: ['key', 'summary'] } },
    conflicts: { type: 'array', items: { type: 'object', properties: { key: { type: 'string' }, description: { type: 'string' }, shards: { type: 'array', items: { type: 'string' } } }, required: ['description'] } },
    xshard_open: { type: 'array', items: { type: 'string' } },
    spot_check: { type: 'string' },
  },
  required: ['summary', 'merged_path', 'ledger_path', 'unique_items', 'semantic_duplicates_removed', 'top_items', 'conflicts', 'xshard_open', 'spot_check'],
}

function normalizePrompt(subId, text, file) {
  const t = text == null ? '' : String(text)
  const truncated = t.length > RETURN_TEXT_CAP
  return [
    'Normalise ONE swarm worker return into the record schema. Mechanical extraction only: never invent, merge, re-rank or judge items.',
    'SHARD: ' + subId,
    'WORKER RETURN (verbatim' + (truncated ? ', TRUNCATED at ' + RETURN_TEXT_CAP + ' chars, read the file for the rest' : '') + '):',
    '<<<',
    t ? clip(t, RETURN_TEXT_CAP) : '(the worker returned nothing)',
    '>>>',
    'SHARD FILE: ' + file + ' - Read it when the return lacks the status line or the items, says the items are in the file, or was truncated. If the return is empty and the file does not exist, status = failed.' + (resume ? '' : ' If the return is empty, ignore any existing file (it is from an earlier run): status = failed.'),
    'Rules:',
    '- status and units from the line "SHARD <id> STATUS <ok|partial|failed> COVERED <n>/<m> ITEMS <k>" (in the return or as the first line of the file). Without that line: ok only if the worker clearly finished its whole scope, partial if it ran out of budget or turns, failed otherwise; units_total = number of units in scope when countable, else 0.',
    '- uncovered: every unit the worker says it did not check ("UNCOVERED: ..." lines or prose), verbatim.',
    '- items: one per reported item; key copied verbatim (if the worker gave none, build "<location>::<short class>" from its own words); summary <= 200 chars; severity and location when given, else "".',
    '- xshard: each "XSHARD: <question> -> <target>" doubt.',
    '- file: the shard file path if it exists, else "".',
    '- notes: <= 300 chars of anomalies (errors, items outside scope that you dropped, missing status line).',
    'Then Write the same JSON object to ' + outDir + '/results/' + subId + '.json (create the directory if needed) before returning it.',
  ].join('\n')
}

// Code fallback when the normaliser agent fails: parse the status line, ITEM, UNCOVERED and XSHARD lines.
function fallbackRecord(subId, text, file, reason) {
  const t = text == null ? '' : String(text)
  const m = /SHARD\s+\S+\s+STATUS\s+(ok|partial|failed)\s+COVERED\s+(\d+)\s*\/\s*(\d+)/i.exec(t)
  const items = []
  const uncovered = []
  const xshard = []
  for (const line of t.split('\n')) {
    const it = /^\s*[-*]?\s*ITEM\s+(.+)$/.exec(line)
    if (it) {
      const parts = it[1].split('|').map(x => x.trim())
      if (parts[0]) items.push({ key: parts[0], summary: clip(parts[1] || parts[0], 200), severity: parts[2] || '', location: parts[3] || '' })
      continue
    }
    const un = /^\s*[-*]?\s*UNCOVERED:\s*(.+)$/i.exec(line)
    if (un) { uncovered.push(un[1].trim()); continue }
    const xs = /XSHARD:\s*(.+?)\s*->\s*(.+)$/.exec(line)
    if (xs) xshard.push({ question: xs[1].trim(), target: xs[2].trim() })
  }
  return {
    shard_id: subId,
    status: m ? m[1].toLowerCase() : (t.trim() ? 'partial' : 'failed'),
    units_total: m ? toInt(m[3]) : 0,
    units_covered: m ? toInt(m[2]) : 0,
    uncovered, items, xshard,
    file: t.trim() ? file : '',
    notes: clip(reason + (m ? '' : '; no status line, coverage unknown'), 300),
    normalized_by: 'code',
  }
}

function sanitize(rec, subId) {
  const r = rec && typeof rec === 'object' ? rec : {}
  let status = ['ok', 'partial', 'failed'].includes(r.status) ? r.status : 'failed'
  const total = toInt(r.units_total)
  let covered = toInt(r.units_covered)
  if (total > 0 && covered > total) covered = total
  if (status === 'ok' && total > 0 && covered < total) status = 'partial'
  const items = (Array.isArray(r.items) ? r.items : []).filter(x => x && !isBlank(x.key || x.summary)).map(x => ({
    key: String(x.key || x.summary).trim(), summary: clip(x.summary || x.key, 200),
    severity: String(x.severity || ''), location: String(x.location || ''),
  }))
  return {
    shard_id: subId, status, units_total: total, units_covered: covered,
    uncovered: (Array.isArray(r.uncovered) ? r.uncovered : []).map(String).map(s => s.trim()).filter(Boolean),
    items,
    xshard: (Array.isArray(r.xshard) ? r.xshard : []).filter(x => x && x.target).map(x => ({ question: String(x.question || ''), target: String(x.target) })),
    file: String(r.file || ''),
    notes: clip(r.notes || '', 300),
    normalized_by: r.normalized_by || 'agent',
  }
}

async function normalizeOne(subId, text, file) {
  const r = await call(normalizePrompt(subId, text, file), {
    label: 'normalize ' + subId, phase: 'Normalize', agentType: 'file-summarizer', schema: RECORD_SCHEMA,
  })
  if (r.value && typeof r.value === 'object') return sanitize(r.value, subId)
  log('normalize ' + subId + ': ' + (r.error || 'no record') + '; using the code parser')
  return sanitize(fallbackRecord(subId, text, file, 'normaliser failed (' + (r.error || 'no record') + ')'), subId)
}

// ---------------------------------------------------------------------------- stages
async function stageWork(sh) {
  const prompt = workerPrompt(sh, sh.brief, '')
  const opts = { label: 'work ' + sh.id, phase: 'Work', agentType: workerType, model: workerModel, effort: workerEffort }
  let r = await call(prompt, opts)
  let attempts = 1
  if (r.error && retry > 0) {
    log('shard ' + sh.id + ': ' + r.error + '; re-running the same brief once (this is its retry)')
    r = await call(prompt, { ...opts, label: 'work ' + sh.id + ' (rerun)' })
    attempts = 2
  }
  return { sh, text: r.error ? null : String(r.value), error: r.error, attempts }
}

async function stageNormalize(w) {
  const file = outDir + '/shards/' + w.sh.id + '.md'
  const rec = await normalizeOne(w.sh.id, w.text, file)
  if (w.error && !w.text) rec.notes = clip((rec.notes ? rec.notes + '; ' : '') + w.error, 300)
  return { sh: w.sh, attempts: w.attempts, rec, files: rec.file ? [rec.file] : [] }
}

async function runSub(sh, sub, effort) {
  const prompt = workerPrompt({ id: sub.id, k: sh.k }, sub.scope, sub.note)
  const r = await call(prompt, { label: 'retry ' + sub.id, phase: 'Work', agentType: workerType, model: workerModel, effort })
  return normalizeOne(sub.id, r.error ? null : String(r.value), outDir + '/shards/' + sub.id + '.md')
}

function finalRecord(sh, attempts, rec, files, retried) {
  return {
    id: sh.id, brief: clip(sh.brief, 200), status: rec.status, attempts,
    units_total: rec.units_total, units_covered: rec.units_covered, uncovered: rec.uncovered,
    items: rec.items, xshard: rec.xshard, files, notes: rec.notes, normalized_by: rec.normalized_by, retried,
  }
}

async function stageRetry(n) {
  const { sh, rec } = n
  if (rec.status === 'ok' || retry === 0 || n.attempts >= 2) return finalRecord(sh, n.attempts, rec, n.files, false)
  if (budget.total && budget.remaining() < RETRY_MIN_BUDGET) {
    log('shard ' + sh.id + ' is ' + rec.status + '; retry skipped (token budget below ' + RETRY_MIN_BUDGET + ')')
    rec.notes = clip(rec.notes + '; retry skipped: budget', 300)
    return finalRecord(sh, n.attempts, rec, n.files, false)
  }
  const units = rec.uncovered
  let subs
  if (rec.status === 'failed' && units.length >= SPLIT_MIN_UNITS) {
    const half = Math.ceil(units.length / 2)
    subs = [
      { id: sh.id + '-r1a', scope: units.slice(0, half).join('\n'), units: half, note: 'retry, first half of failed shard ' + sh.id },
      { id: sh.id + '-r1b', scope: units.slice(half).join('\n'), units: units.length - half, note: 'retry, second half of failed shard ' + sh.id },
    ]
  } else if (units.length) {
    subs = [{ id: sh.id + '-r1', scope: units.join('\n'), units: units.length, note: 'retry of ' + sh.id + ' covering ONLY its previously uncovered units' }]
  } else {
    subs = [{ id: sh.id + '-r1', scope: sh.brief, units: 0, note: 'second and last attempt; the first ended ' + rec.status + (rec.notes ? ' (' + clip(rec.notes, 200) + ')' : '') + '. Grep first, read only the hits, and report partial progress honestly' }]
  }
  log('shard ' + sh.id + ' ' + rec.status + ' (' + rec.units_covered + '/' + rec.units_total + '); retrying as ' + subs.map(s => s.id).join(' + '))
  const effort = bumpEffort(workerEffort)
  const outs = (await parallel(subs.map(sub => () => runSub(sh, sub, effort)))).map((o, i) => o || sanitize(fallbackRecord(subs[i].id, null, '', 'retry stage threw'), subs[i].id))

  // Combine original + retry attempts.
  const items = rec.items.concat(...outs.map(o => o.items))
  const xshard = rec.xshard.concat(...outs.map(o => o.xshard))
  const files = n.files.concat(outs.map(o => o.file).filter(Boolean))
  let status, covered, total, uncovered
  if (rec.units_total > 0) {
    total = rec.units_total
    if (units.length) {
      // Remainder retry: the retry units are disjoint from what attempt 1 covered, so coverage adds.
      const prior = Math.max(0, Math.min(rec.units_covered, total - units.length))
      const gained = outs.reduce((a, o, i) => a + (o.units_total > 0 ? Math.min(o.units_covered, subs[i].units) : (o.status === 'ok' ? subs[i].units : 0)), 0)
      covered = Math.min(total, prior + gained)
    } else {
      // Whole-shard retry: attempt 2 re-covers the same units, so take the better attempt, never the sum.
      const o = outs[0]
      covered = Math.max(rec.units_covered, o.units_total > 0 ? Math.min(total, o.units_covered) : (o.status === 'ok' ? total : 0))
    }
    uncovered = [].concat(...outs.map(o => o.uncovered))
    status = covered >= total ? 'ok' : (covered > 0 ? 'partial' : 'failed')
  } else {
    total = 0
    covered = 0
    uncovered = [].concat(...outs.map(o => o.uncovered))
    status = outs.every(o => o.status === 'ok') ? 'ok' : (outs.some(o => o.status !== 'failed') || rec.status === 'partial' ? 'partial' : 'failed')
  }
  const notes = clip([rec.notes].concat(outs.map(o => o.shard_id + ': ' + o.status + (o.notes ? ' ' + o.notes : ''))).filter(Boolean).join('; '), 300)
  return finalRecord(sh, n.attempts + 1, { status, units_total: total, units_covered: covered, uncovered, items, xshard, notes, normalized_by: rec.normalized_by }, files, true)
}

// ---------------------------------------------------------------------------- run shards
phase('Work')
const piped = await pipeline(shards, stageWork, stageNormalize, stageRetry)
const records = piped.map((r, i) => r || finalRecord(shards[i], 1, sanitize(fallbackRecord(shards[i].id, null, '', 'pipeline stage threw'), shards[i].id), [], false))

// ---------------------------------------------------------------------------- dedup + ledger (code)
const byKey = new Map()
let rawItems = 0
for (const r of records) {
  for (const it of r.items) {
    rawItems++
    const k = normKey(it.key) || normKey(it.summary)
    if (!k) continue
    const e = byKey.get(k)
    if (!e) { byKey.set(k, { key: it.key, summary: it.summary, severity: it.severity, location: it.location, shards: [r.id], count: 1 }); continue }
    e.count++
    if (!e.shards.includes(r.id)) e.shards.push(r.id)
    if (sevRank(it.severity) < sevRank(e.severity)) e.severity = it.severity
    if (it.summary.length > e.summary.length) e.summary = it.summary
    if (!e.location && it.location) e.location = it.location
  }
}
const deduped = [...byKey.values()].sort((a, b) => (sevRank(a.severity) - sevRank(b.severity)) || (b.shards.length - a.shards.length) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))

let unitsTotal = 0
let unitsCovered = 0
let unitsReported = 0
for (const r of records) {
  if (r.units_total > 0) { unitsReported++; unitsTotal += r.units_total; unitsCovered += Math.min(r.units_covered, r.units_total) }
  else { unitsTotal += 1; unitsCovered += r.status === 'ok' ? 1 : 0 }
}
unitsTotal += capped.length
const countBy = st => records.filter(r => r.status === st).length
const coverage = {
  shards_total: S + capped.length + rejected.length,
  shards_run: S,
  shards_ok: countBy('ok'),
  shards_partial: countBy('partial'),
  shards_failed: countBy('failed'),
  shards_capped: capped.map(s => s.id),
  shards_rejected: rejected.map(r => r.id),
  units_total: unitsTotal,
  units_covered: unitsCovered,
  pct: unitsTotal ? Math.round(1000 * unitsCovered / unitsTotal) / 10 : 0,
  unit_counts_reported: unitsReported + '/' + S + ' shards reported unit counts; the others count as one unit each',
  retries: records.filter(r => r.retried).length,
  raw_items: rawItems,
  unique_by_key: deduped.length,
}
const ledgerRows = records.map(r => '| ' + [r.id, r.units_total > 0 ? String(r.units_total) : '?', workerType + ' / ' + (workerModel || 'default') + ' / ' + (workerEffort || 'default'),
  String(r.attempts), r.status, r.units_total > 0 ? r.units_covered + '/' + r.units_total : (r.status === 'ok' ? 'all' : '?'), String(r.items.length),
  r.files.join(' ') || '-', clip(r.notes, 120).replace(/\|/g, '/')].join(' | ') + ' |')
  .concat(capped.map(s => '| ' + s.id + ' | ? | - | 0 | dropped | 0/? | - | - | capped by maxShards=' + maxShards + ' |'))
  .concat(rejected.map(r => '| ' + r.id + ' | 0 | - | 0 | dropped | - | - | - | ' + r.reason + ' |'))
const ledgerMd = ['| shard | units | agent / model / effort | attempts | status | covered | items | file | note |', '|---|---|---|---|---|---|---|---|---|'].concat(ledgerRows).join('\n')
const coverageLine = 'Coverage ' + coverage.units_covered + '/' + coverage.units_total + ' units (' + coverage.pct + '%); shards ok ' + coverage.shards_ok + ', partial ' + coverage.shards_partial +
  ', failed ' + coverage.shards_failed + ', capped ' + capped.length + ', rejected ' + rejected.length + '; items raw ' + rawItems + ' -> ' + deduped.length + ' unique by key.'
log(coverageLine)

const failed = records.filter(r => r.status !== 'ok').map(r => ({ id: r.id, status: r.status, attempts: r.attempts, reason: r.notes || r.status, uncovered: r.uncovered }))
  .concat(capped.map(s => ({ id: s.id, status: 'dropped', attempts: 0, reason: 'capped by maxShards=' + maxShards, uncovered: [] })))
  .concat(rejected)
const perShard = records.map(r => ({ id: r.id, status: r.status, attempts: r.attempts, units_covered: r.units_covered, units_total: r.units_total, items: r.items.length, files: r.files, notes: r.notes, normalized_by: r.normalized_by }))

// Early exit: nothing usable came back.
if (!records.some(r => r.status !== 'failed')) {
  log('every shard failed; merge skipped')
  return { started: true, outDir, merged: null, reason: 'all shards failed; merge skipped', perShard, failed, coverage: { ...coverage, ledger: ledgerMd } }
}

// ---------------------------------------------------------------------------- XSHARD follow-ups (cross-item, after the barrier)
const xsGroups = new Map()
for (const r of records) for (const x of r.xshard) {
  const t = normKey(x.target)
  if (!t) continue
  if (!xsGroups.has(t)) xsGroups.set(t, { target: x.target, questions: [] })
  xsGroups.get(t).questions.push({ from: r.id, question: x.question })
}
const xsAll = [...xsGroups.values()].sort((a, b) => (b.questions.length - a.questions.length) || (a.target < b.target ? -1 : 1))
let xsHot = xsAll.filter(g => g.questions.length >= XSHARD_MIN_QUESTIONS)
if (xsHot.length > XSHARD_MAX_FOLLOWUPS) {
  log('XSHARD: ' + xsHot.length + ' targets qualify for a follow-up; running the top ' + XSHARD_MAX_FOLLOWUPS + ', the rest stay open: ' + xsHot.slice(XSHARD_MAX_FOLLOWUPS).map(g => g.target).join(', '))
  xsHot = xsHot.slice(0, XSHARD_MAX_FOLLOWUPS)
}
let followups = []
if (xsHot.length && !(budget.total && budget.remaining() < RETRY_MIN_BUDGET)) {
  followups = (await parallel(xsHot.map((g, i) => () => call([
    'SWARM GOAL: ' + task,
    'CROSS-SHARD FOLLOW-UP ' + (i + 1) + ' of ' + xsHot.length + ' on target: ' + g.target,
    'Several shards could not answer these questions because the target was outside their scope:',
    g.questions.map(q => '- [' + q.from + '] ' + q.question).join('\n'),
    'Answer each question with evidence (path:line, URL, or command output). Report any new item in the ITEM FORMAT: "ITEM <key> | <summary> | <severity> | <location>" with key per: ' + keySpec + '.',
    'Write details to ' + outDir + '/xshard/' + slugify(g.target) + '.md. Do not spawn subagents. Return at most 40 lines.',
  ].join('\n'), { label: 'xshard ' + clip(g.target, 40), phase: 'Work', agentType: workerType, model: workerModel, effort: workerEffort }))))
    .map((r, i) => ({ target: xsHot[i].target, questions: xsHot[i].questions.length, answer: r && !r.error ? clip(r.value, 6000) : null, error: r ? r.error : 'threw' }))
} else if (xsHot.length) {
  log('XSHARD follow-ups skipped (token budget); targets stay open')
}
const xsOpen = xsAll.filter(g => !followups.some(f => f.target === g.target && f.answer))

// ---------------------------------------------------------------------------- merge (swarm-coordinator, merge mode)
phase('Merge')
let mergedOut = null
if (!deduped.length && !followups.some(f => f.answer)) {
  log('0 items across all shards; merge agent skipped, ledger returned inline')
  mergedOut = {
    summary: 'No items reported. ' + coverage.shards_ok + ' shard(s) finished with status ok, so their zero-item result is evidence of absence for their scope; partial/failed shards are not.',
    merged_path: '', ledger_path: '', unique_items: 0, semantic_duplicates_removed: 0, top_items: [], conflicts: [], xshard_open: xsOpen.map(g => g.target), spot_check: 'n/a',
  }
} else {
  const lines = deduped.map(d => JSON.stringify({ key: d.key, severity: d.severity, location: d.location, shards: d.shards, summary: d.summary }))
  let inline = lines.join('\n')
  if (inline.length > INLINE_ITEMS_CAP) {
    log('merge prompt: ' + deduped.length + ' deduped items (' + inline.length + ' chars) too large to inline; coordinator merges from results/*.json')
    // Code-fallback shards have no results/<id>.json: inline their items so the jq merge cannot drop them.
    const codeIds = records.filter(r => r.normalized_by === 'code').map(r => r.id)
    const codeAll = deduped.filter(d => d.shards.some(x => codeIds.includes(x))).map(d => JSON.stringify({ key: d.key, severity: d.severity, location: d.location, shards: d.shards, summary: d.summary }))
    let codeChars = 0
    const codeLines = codeAll.filter(l => (codeChars += l.length + 1) <= 4 * INLINE_ITEMS_CAP)
    if (codeLines.length < codeAll.length) codeLines.push('(' + (codeAll.length - codeLines.length) + ' more: take the ITEM lines of shards/<id>.md for these ids)')
    inline = '(too large to inline: ' + deduped.length + ' items, ' + inline.length + ' chars) Build the list from ' + outDir + '/results/*.json with jq (only ids in the ledger and their -r1* retries; others are from earlier runs), e.g.\n' +
      'jq -s "[.[].items[] ] | group_by(.key | ascii_downcase) | map(.[0] + {n: length})" ' + outDir + '/results/*.json\n' +
      'Check that results/<id>.json exists for every ledger id not listed as code fallback; for a missing one, take its ITEM lines from shards/<id>.md. Reconcile: raw items found must equal ' + rawItems + '; report any difference in ledger.md.' +
      (codeLines.length ? '\nShards normalised by the code fallback (' + codeIds.join(', ') + ') have no results/*.json; merge these items too:\n' + codeLines.join('\n') : '')
  }
  const fu = followups.length ? followups.map(f => '### target ' + f.target + ' (' + f.questions + ' questions)\n' + (f.answer || '(follow-up failed: ' + f.error + ')')).join('\n\n') : '(none run)'
  const mergePrompt = [
    'MERGE MODE (final stage of the swarm-run workflow). Do not spawn workers, do not re-partition, do not redo shard work; failed or partial shards are reported, not redone.',
    'SWARM GOAL: ' + clip(task, 3000),
    'RUN DIR: ' + outDir,
    '  shards/<id>.md      full worker outputs (read only to spot-check or to resolve a conflict)',
    '  results/<id>.json   normalised records (status, unit counts, keyed items); missing for shards normalised by the code fallback: ' + (records.filter(r => r.normalized_by === 'code').map(r => r.id).join(', ') || 'none'),
    'MERGE INSTRUCTIONS: ' + mergeSpec,
    'DEDUP KEY: ' + keySpec,
    'Exact-key duplicates are already merged in code (' + rawItems + ' raw items -> ' + deduped.length + ' unique keys). Your job: (1) semantic duplicates whose keys are worded differently but name the same thing (merge them, keep the union of shards, count them); (2) conflicts where shards contradict each other (list them, never resolve silently); (3) fold in the XSHARD follow-up answers; (4) order by severity, then location.',
    '',
    'COVERAGE LEDGER (computed in code; authoritative: copy it, do not recompute coverage from prose):',
    ledgerMd,
    coverageLine,
    '',
    'ITEMS AFTER EXACT-KEY DEDUP (JSON lines):',
    inline,
    '',
    'XSHARD FOLLOW-UPS:',
    fu,
    'XSHARD STILL OPEN: ' + (xsOpen.map(g => g.target + ' (' + g.questions.length + ')').join(', ') || 'none'),
    '',
    'WRITE:',
    '- ' + outDir + '/merged.json: array of {key, summary, severity, location, shards}; and ' + outDir + '/merged.md: a readable table in the same order.',
    '- ' + outDir + '/ledger.md: the ledger above, the reconciliation line (units covered + uncovered + dropped = total), the dedup line (raw -> exact-key unique -> semantic unique), conflicts, open XSHARD targets.',
    'Spot-check 2-3 merged entries against their shard files and report the outcome in spot_check.',
    'Return top_items: at most 25, highest severity first. summary: 5-15 lines including the coverage line.',
  ].join('\n')
  const m = await call(mergePrompt, { label: 'merge ' + deduped.length + ' items', phase: 'Merge', agentType: 'swarm-coordinator', schema: MERGE_SCHEMA })
  if (m.value && typeof m.value === 'object') mergedOut = m.value
  else {
    log('merge agent failed (' + m.error + '); returning the code-level merge only')
    mergedOut = {
      summary: 'Merge agent failed; items below are deduplicated by exact key only (no semantic dedup, no conflict detection). ' + coverageLine,
      merged_path: '', ledger_path: '', unique_items: deduped.length, semantic_duplicates_removed: 0,
      top_items: deduped.slice(0, 25).map(d => ({ key: d.key, summary: d.summary, severity: d.severity, shards: d.shards })),
      conflicts: [], xshard_open: xsOpen.map(g => g.target), spot_check: 'not run', merge_error: m.error,
    }
  }
}

if (deduped.length > RETURN_ITEMS_CAP) log('return value carries the first ' + RETURN_ITEMS_CAP + ' of ' + deduped.length + ' deduped items (severity order); the full list is in merged.json / results/*.json')
return {
  started: true,
  outDir,
  merged: {
    ...mergedOut,
    raw_items: rawItems,
    unique_by_key: deduped.length,
    items: deduped.slice(0, RETURN_ITEMS_CAP),
    items_truncated: deduped.length > RETURN_ITEMS_CAP,
    xshard_followups: followups.map(f => ({ target: f.target, questions: f.questions, answered: !!f.answer })),
  },
  perShard,
  failed,
  coverage: { ...coverage, line: coverageLine, ledger: ledgerMd },
}
