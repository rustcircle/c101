export const meta = {
  name: 'manuscript-review',
  description: 'Whole-manuscript review of a markdown fiction project: index and validate the chapters, run copy-editor (orthography, punctuation, grammar, consistency) and prose-stylist (show-not-tell, purple prose, generic/AI-sounding prose, filter words, rhythm) on every chapter in parallel, report-only, then manuscript-reviewer merges every chapter report with a developmental pass into one prioritized report in the project reviews/ folder.',
  whenToUse: 'A draft or revised manuscript (chapters/NNN_slug.md layout, or a custom layout declared in manuscript.md) needs a full editorial pass with chapter:line anchors, without editing any chapter file. Main thread only. args {project: path to the project root (folder with manuscript.md), chapters?: "all" | ["001","007"], checks?: ["copyedit","style","developmental"], maxChapters?: 120}. For one chapter or one kind of check call copy-editor, prose-stylist or manuscript-reviewer directly.',
  phases: [
    { title: 'Index', detail: 'writing-project-builder validates the project and lists the chapters (read-only) and returns the report timestamp every agent uses' },
    { title: 'Analyze', detail: 'per chapter, copy-editor and prose-stylist in parallel; each writes reviews/<stamp>-<kind>-NNN.md and returns counts and its top issues' },
    { title: 'Synthesize', detail: 'manuscript-reviewer merges the chapter reports, adds the developmental pass and writes reviews/<stamp>-manuscript-review.md' },
  ],
}

// ---------------------------------------------------------------------------
// Index -> Analyze (pipelined per chapter, two analysts in parallel) -> Synthesize.
// Report-only: no agent may edit chapter files in this workflow. Tallies run in code.
// ---------------------------------------------------------------------------

const CHECKS = ['copyedit', 'style', 'developmental']
const DEFAULT_MAX_CHAPTERS = 120
const HARD_MAX_CHAPTERS = 400   // 2 analysts per chapter + 2 fixed agents stay under the 1000-agent cap
const SUMMARY_CAP = 2500        // chars of one chapter summary passed to the synthesis step
const SEVERITIES = ['minor', 'moderate', 'major']

const notes = []
function note(msg) { notes.push(msg); log(msg) }
function clip(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n) + '…' : s }
function cleanOpts(o) {
  const r = {}
  for (const k of Object.keys(o)) if (o[k] !== undefined && o[k] !== null && o[k] !== '') r[k] = o[k]
  return r
}
async function call(prompt, opts) {
  try {
    return await agent(prompt, cleanOpts(opts))
  } catch (e) {
    note(`${opts.label}: agent call failed (${clip((e && e.message) || e, 160)})`)
    return null
  }
}
function parseArgs(raw) {
  let a = raw
  if (typeof a === 'string') {
    try { a = JSON.parse(a) } catch (e) { a = { project: a } }
    if (typeof a === 'string') a = { project: a }
  }
  return a && typeof a === 'object' && !Array.isArray(a) ? a : {}
}

const A = parseArgs(args)
const USAGE = 'args {project: "<path to the folder with manuscript.md>", chapters?: "all" | ["001", ...], checks?: ["copyedit","style","developmental"], maxChapters?: 120}'
if (typeof A.project !== 'string' || !A.project.trim()) {
  return { started: false, reason: 'missing args.project (the manuscript project root)', next: USAGE }
}
const PROJECT = A.project.trim()
const checks = Array.isArray(A.checks) && A.checks.length ? A.checks.map(c => String(c).toLowerCase()) : CHECKS.slice()
const unknown = checks.filter(c => !CHECKS.includes(c))
if (unknown.length) {
  return { started: false, reason: `unknown check(s): ${unknown.join(', ')}`, next: `checks is a subset of ${CHECKS.join(', ')}` }
}
let maxChapters = Number.isInteger(A.maxChapters) && A.maxChapters > 0 ? A.maxChapters : DEFAULT_MAX_CHAPTERS
if (maxChapters > HARD_MAX_CHAPTERS) { note(`maxChapters ${maxChapters} capped at ${HARD_MAX_CHAPTERS}`); maxChapters = HARD_MAX_CHAPTERS }
const wanted = Array.isArray(A.chapters) ? new Set(A.chapters.map(c => String(c).padStart(3, '0'))) : null

const SCRIPT_NOTE = 'Resolve the stack root as $CLAUDE_PROJECT_DIR when it contains .claude/skills/manuscript-project, else ~/.claude/stack, and run scripts with `uv run --python 3.13 python <stack>/.claude/skills/...`.'
const REPORT_ONLY = 'REPORT-ONLY RUN: do not edit, rename or create any file in the chapter folder; write only your report file.'

// ---------------------------------------------------------------- Index
phase('Index')
const INDEX_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    error: { type: 'string' },
    stamp: { type: 'string', description: 'output of `date +%Y%m%d-%H%M`, used in every report name of this run' },
    chapter_dir: { type: 'string' },
    chapters: {
      type: 'array',
      items: {
        type: 'object',
        properties: { number: { type: 'string' }, file: { type: 'string' }, title: { type: 'string' }, words: { type: 'integer' } },
        required: ['number', 'file'],
      },
    },
    warnings: { type: 'array', items: { type: 'string' } },
  },
  required: ['ok', 'stamp', 'chapters'],
}
const index = await call(
  `Validate and index the manuscript project at ${PROJECT}. ${SCRIPT_NOTE}\n` +
  `1. Run \`manuscript.py validate ${PROJECT}\` and \`manuscript.py index ${PROJECT}\` (never --write, never renumber: this run is read-only).\n` +
  `2. Run \`date +%Y%m%d-%H%M\` once and return its output as stamp.\n` +
  `3. Return ok=false with the validation errors in error if the project has no manuscript.md, no chapter folder or validation errors that make chapters ambiguous (duplicate numbers); warnings (gaps, missing bible files) go in warnings and keep ok=true.\n` +
  `Return chapters in reading order with number as the 3-digit string, file as the path relative to the project, title and words.`,
  { agentType: 'writing-project-builder', label: 'index', phase: 'Index', schema: INDEX_SCHEMA },
)
if (!index || !index.ok || !Array.isArray(index.chapters)) {
  return { started: false, reason: `project ${PROJECT} did not validate: ${clip(index && index.error ? index.error : 'index agent returned nothing', 400)}`, next: 'Fix the layout with writing-project-builder (manuscript.py validate shows the errors), then rerun.', notes }
}
for (const w of index.warnings || []) note(`index warning: ${clip(w, 200)}`)
const STAMP = /^\d{8}-\d{4}$/.test(String(index.stamp || '')) ? index.stamp : 'run'
if (STAMP === 'run') note('index returned no usable timestamp; reports are named reviews/run-<kind>-NNN.md')

let chapters = index.chapters.filter(c => c && typeof c.file === 'string' && c.file)
  .map(c => ({ number: String(c.number || '').padStart(3, '0'), file: c.file, title: c.title || '', words: Number.isInteger(c.words) ? c.words : null }))
if (wanted) {
  const missing = [...wanted].filter(n => !chapters.some(c => c.number === n))
  if (missing.length) note(`requested chapter(s) not found: ${missing.join(', ')}`)
  chapters = chapters.filter(c => wanted.has(c.number))
}
if (chapters.length > maxChapters) {
  note(`${chapters.length} chapters; analysing the first ${maxChapters} (raise maxChapters to cover the rest)`)
  chapters = chapters.slice(0, maxChapters)
}
if (!chapters.length) {
  return { started: false, reason: 'no chapters to review', next: 'Check args.chapters against `manuscript.py index`, or add chapters first.', notes }
}
log(`project ${PROJECT}: ${chapters.length} chapter(s); checks ${checks.join(', ')}; stamp ${STAMP}`)

// ---------------------------------------------------------------- Analyze
const ANALYSIS_SCHEMA = {
  type: 'object',
  properties: {
    report: { type: 'string', description: 'path of the report file you wrote, relative to the project' },
    total: { type: 'integer', minimum: 0 },
    by_category: {
      type: 'array',
      items: {
        type: 'object',
        properties: { category: { type: 'string' }, count: { type: 'integer', minimum: 0 }, severity: { type: 'string', enum: SEVERITIES } },
        required: ['category', 'count', 'severity'],
      },
    },
    top: {
      type: 'array',
      maxItems: 5,
      items: {
        type: 'object',
        properties: { line: { type: 'integer' }, category: { type: 'string' }, excerpt: { type: 'string' }, suggestion: { type: 'string' } },
        required: ['line', 'category', 'excerpt'],
      },
    },
    strengths: { type: 'array', maxItems: 5, items: { type: 'string' } },
  },
  required: ['report', 'total', 'by_category', 'top'],
}
const ANALYSTS = [
  { check: 'copyedit', agentType: 'copy-editor', kind: 'copyedit',
    task: 'Copyedit this chapter: US spelling and typos, punctuation (dialogue, commas, dashes, ellipses, quotes), grammar and syntax, and consistency against style-sheet.md and the bible (names, terms, capitalization, hyphenation, numbers). Use prose_check.py mechanics on the chapter for candidates and read every flagged line in context; consistency across chapters is checked once in the synthesis step.' },
  { check: 'style', agentType: 'prose-stylist', kind: 'style',
    task: 'Analyse the prose of this chapter: show-not-tell, purple prose, generic or AI-sounding prose, filter words and weak verbs, dialogue tags, repetition and rhythm. Use prose_check.py style and readability on the chapter for candidates and judge each in context (deep POV and deliberate telling can be right); give before/after suggestions for the top issues.' },
].filter(a => checks.includes(a.check))

let analyses = []
if (ANALYSTS.length) {
  phase('Analyze')
  analyses = await pipeline(chapters, ch => parallel(ANALYSTS.map(an => () => call(
    `${an.task}\nProject: ${PROJECT}\nChapter ${ch.number}${ch.title ? ` "${ch.title}"` : ''}: ${ch.file}\n` +
    `${REPORT_ONLY}\nWrite your report to ${PROJECT}/reviews/${STAMP}-${an.kind}-${ch.number}.md in the pack's report format (summary table, findings with file:line anchors, strengths, next steps). ${SCRIPT_NOTE}\n` +
    `Return the report path, the total and per-category counts, at most 5 top issues (line, category, excerpt <= 20 words, suggestion) and up to 5 concrete strengths.`,
    { agentType: an.agentType, label: `${an.kind}:${ch.number}`, phase: 'Analyze', schema: ANALYSIS_SCHEMA },
  ).then(r => ({ kind: an.kind, chapter: ch.number, file: ch.file, result: r })))))
}

const rows = []
const failures = []
const totals = {}
for (const per of analyses || []) {
  for (const a of per || []) {
    if (!a) continue
    if (!a.result || typeof a.result.report !== 'string') { failures.push({ chapter: a.chapter, kind: a.kind }); continue }
    rows.push(a)
    for (const c of a.result.by_category || []) {
      const key = `${a.kind}:${String(c.category).toLowerCase()}`
      totals[key] = (totals[key] || 0) + (Number.isInteger(c.count) ? c.count : 0)
    }
  }
}
if (failures.length) note(`${failures.length} chapter analysis call(s) returned nothing: ${failures.map(f => `${f.kind}:${f.chapter}`).join(', ')}`)
const ranked = Object.entries(totals).sort((x, y) => y[1] - x[1] || (x[0] < y[0] ? -1 : 1)).map(([k, n]) => ({ category: k, count: n }))

// ---------------------------------------------------------------- Synthesize
let synthesis = null
if (checks.includes('developmental') || rows.length) {
  phase('Synthesize')
  const digest = rows.map(r => clip(JSON.stringify({ kind: r.kind, chapter: r.chapter, report: r.result.report, total: r.result.total, top: r.result.top, strengths: r.result.strengths }), SUMMARY_CAP))
  const SYNTH_SCHEMA = {
    type: 'object',
    properties: {
      report: { type: 'string' },
      verdict: { type: 'string', description: 'two or three sentences on the state of the manuscript' },
      priorities: {
        type: 'array',
        maxItems: 10,
        items: {
          type: 'object',
          properties: { rank: { type: 'integer', minimum: 1 }, scope: { type: 'string' }, issue: { type: 'string' }, action: { type: 'string' } },
          required: ['rank', 'scope', 'issue', 'action'],
        },
      },
    },
    required: ['report', 'verdict', 'priorities'],
  }
  synthesis = await call(
    `Synthesize the manuscript review of ${PROJECT} (chapters ${chapters.map(c => c.number).join(', ')}). ${REPORT_ONLY}\n` +
    (checks.includes('developmental')
      ? 'Do the developmental pass yourself: structure, plot logic, stakes, pacing (use `manuscript.py stats`), scene and sequel, POV and tense discipline, character arcs and motivation, continuity against the bible and timeline; run `prose_check.py consistency` once on the project for cross-chapter name and term variants. Offload whole-book reading to file-summarizer if the chapters exceed your context.\n'
      : 'No developmental pass was requested: merge the chapter reports only.\n') +
    `Chapter analyses (per-category totals across chapters, highest first): ${JSON.stringify(ranked.slice(0, 40))}\n` +
    `Per-chapter summaries (open the report files for detail):\n${digest.join('\n')}\n` +
    `Write ${PROJECT}/reviews/${STAMP}-manuscript-review.md: verdict, global issues before local ones, a prioritized action list (at most 10), recurring patterns across chapters with examples and links to the chapter reports, strengths. ${SCRIPT_NOTE}\n` +
    'Return the report path, the verdict and the prioritized actions.',
    { agentType: 'manuscript-reviewer', label: 'synthesize', phase: 'Synthesize', schema: SYNTH_SCHEMA },
  )
  if (!synthesis) note('synthesis returned nothing; the chapter reports are still in reviews/')
}

return {
  started: true,
  completed: true,
  project: PROJECT,
  stamp: STAMP,
  checks,
  chapters: chapters.length,
  report: synthesis && synthesis.report ? synthesis.report : null,
  verdict: synthesis && synthesis.verdict ? clip(synthesis.verdict, 600) : null,
  priorities: synthesis && Array.isArray(synthesis.priorities) ? synthesis.priorities.slice(0, 10) : [],
  totals: ranked.slice(0, 30),
  chapterReports: rows.map(r => ({ chapter: r.chapter, kind: r.kind, report: r.result.report, total: r.result.total })),
  failures,
  notes,
}
