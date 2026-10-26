export const meta = {
  name: 'research-sweep',
  description: 'Multi-modal research sweep: deep-researcher decomposes the question; per sub-question web-searcher (Exa/Jina), paper-researcher (arXiv/SSRN) and web-crawler (Spider on top domains) feed a cited claim extractor; claims are deduplicated and fact-checked; a completeness critic loops until dry; deep-researcher writes the cited report.',
  whenToUse: 'A research question that needs many sources across modalities and an evidence-graded, cited report on disk: surveys, state of the art, decision memos, regulatory or market landscapes. args {question, depth?: "quick"|"standard"|"exhaustive" (default standard), outFile?: path (default .stack/out/research-sweep/<slug>.md), scope?: string, domains?: [host or host/path to crawl], maxSubQuestions?, verifyCap?, criticRounds?, runTag?}. For a single fact use quick-researcher; for one claim use fact-checker.',
  phases: [
    { title: 'Plan', detail: 'deep-researcher decomposes the question into MECE sub-questions with modalities, seed domains and starting queries' },
    { title: 'Sweep', detail: 'per sub-question: web-searcher (Exa neural + Jina keyword) and paper-researcher (Jina arXiv/SSRN) in parallel, then web-crawler (Spider) on the top authoritative domains' },
    { title: 'Extract', detail: 'source-summarizer deep-reads the best sources and extracts atomic claims with quotes, dates, importance and volatility' },
    { title: 'Verify', detail: 'claims deduplicated across sub-questions in code; fact-checker on the highest-risk key claims (two lenses at exhaustive depth)' },
    { title: 'Critic', detail: 'quality-control as completeness critic turns coverage gaps into new sub-questions; loop until a dry round or the depth cap' },
    { title: 'Synthesize', detail: 'deep-researcher writes claims.md, sources.md and the cited report to outFile' },
  ],
}

// ---------------------------------------------------------------------------
// Research sweep. Sub-questions flow through Sweep -> Extract independently
// (pipeline). The claim ledger is merged in code (barrier justified: dedup
// across sub-questions before paying for verification).
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
    next: 'Run Workflow research-sweep with args {question: "What are the production trade-offs of HNSW vs IVF-PQ vs DiskANN at billion scale in 2026?", depth: "standard", outFile: ".stack/out/research-sweep/vector-index.md"}',
  }
}

const DEPTHS = {
  quick: { maxSubQ: 4, modalities: ['web', 'papers'], maxSources: 6, readTop: 4, maxClaimsPerSq: 8, crawlDomains: 0, crawlPagesPerDomain: 0, verifyCap: 8, verifyLenses: 1, criticRounds: 1, gapsPerRound: 2 },
  standard: { maxSubQ: 6, modalities: ['web', 'papers', 'crawl'], maxSources: 10, readTop: 6, maxClaimsPerSq: 12, crawlDomains: 2, crawlPagesPerDomain: 30, verifyCap: 20, verifyLenses: 1, criticRounds: 2, gapsPerRound: 3 },
  exhaustive: { maxSubQ: 10, modalities: ['web', 'papers', 'crawl'], maxSources: 15, readTop: 10, maxClaimsPerSq: 20, crawlDomains: 3, crawlPagesPerDomain: 60, verifyCap: 50, verifyLenses: 2, criticRounds: 4, gapsPerRound: 5 },
}
let DEPTH = typeof A.depth === 'string' ? A.depth.trim().toLowerCase() : 'standard'
if (!DEPTHS[DEPTH]) { note(`unknown depth "${A.depth}"; using standard`); DEPTH = 'standard' }
function clampInt(v, lo, hi, dflt) {
  const n = Number(v)
  if (!Number.isFinite(n)) return dflt
  return Math.max(lo, Math.min(hi, Math.round(n)))
}
const CFG = Object.assign({}, DEPTHS[DEPTH])
if (A.maxSubQuestions !== undefined) CFG.maxSubQ = clampInt(A.maxSubQuestions, 1, 16, CFG.maxSubQ)
if (A.verifyCap !== undefined) CFG.verifyCap = clampInt(A.verifyCap, 0, 120, CFG.verifyCap)
if (A.criticRounds !== undefined) CFG.criticRounds = clampInt(A.criticRounds, 0, 6, CFG.criticRounds)

function slugify(s, max) {
  const n = max || 48
  const t = String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  if (t.length <= n) return t || 'research'
  const cut = t.slice(0, n)
  const at = cut.lastIndexOf('-')
  return (at >= n / 2 ? cut.slice(0, at) : cut).replace(/-+$/g, '') || 'research'
}
const SLUG = slugify(QUESTION, 48)
const TAG = typeof A.runTag === 'string' && A.runTag.trim() ? '-' + slugify(A.runTag, 24) : ''
const RUN_DIR = `.stack/out/research-sweep/${SLUG}${TAG}`
const OUT_FILE = typeof A.outFile === 'string' && A.outFile.trim() ? A.outFile.trim() : `.stack/out/research-sweep/${SLUG}${TAG}.md`
if (!TAG) note(`working directory ${RUN_DIR} (pass runTag to keep separate runs of the same question apart)`)
log(`depth=${DEPTH}: <=${CFG.maxSubQ} sub-questions, modalities ${CFG.modalities.join('+')}, verify <=${CFG.verifyCap} claims x${CFG.verifyLenses} lens, <=${CFG.criticRounds} critic rounds; report -> ${OUT_FILE}`)

// ---------------- helpers ----------------
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
function numbersOf(s) {
  return (String(s || '').match(/\d+(?:[.,]\d+)?/g) || []).map(x => x.replace(',', '.')).sort().join('|')
}
function canonUrl(u) {
  let s = String(u || '').trim()
  s = s.replace(/#.*$/, '')
  s = s.replace(/([?&])(utm_[a-z]+|ref|fbclid|gclid)=[^&]*/gi, '$1').replace(/[?&]+$/, '').replace(/\?&/, '?')
  s = s.replace(/^http:\/\//i, 'https://').replace(/^(https:\/\/)www\./i, '$1')
  s = s.replace(/\/+$/, '')
  const m = /^(https:\/\/)([^/]+)(.*)$/i.exec(s)
  return m ? m[1] + m[2].toLowerCase() + m[3] : s
}
// Approximate registrable domain: the "origin group" used for independence of sources.
function originOf(u) {
  const m = /^[a-z]+:\/\/([^/?#]+)/i.exec(String(u || ''))
  let host = (m ? m[1] : String(u || '')).toLowerCase().replace(/^www\./, '').replace(/:\d+$/, '')
  const parts = host.split('.').filter(Boolean)
  if (parts.length <= 2) return host
  const tld = parts[parts.length - 1], sld = parts[parts.length - 2]
  if (tld.length === 2 && ['co', 'com', 'ac', 'gov', 'org', 'net', 'edu', 'or', 'ne', 'go'].includes(sld)) return parts.slice(-3).join('.')
  return parts.slice(-2).join('.')
}
function hostPath(d) {
  return String(d || '').trim().toLowerCase().replace(/^[a-z]+:\/\//, '').replace(/^www\./, '').replace(/[?#].*$/, '').replace(/\/+$/, '')
}
const NO_SITEWIDE_CRAWL = ['wikipedia.org', 'youtube.com', 'x.com', 'twitter.com', 'linkedin.com', 'facebook.com', 'reddit.com', 'medium.com', 'quora.com', 'stackoverflow.com', 'news.ycombinator.com', 'google.com', 'amazon.com', 'arxiv.org', 'github.com', 'substack.com']
function crawlable(d) {
  const hp = hostPath(d)
  if (!hp || !hp.includes('.')) return false
  const host = hp.split('/')[0]
  const hasPath = hp.includes('/')
  return hasPath || !NO_SITEWIDE_CRAWL.some(b => host === b || host.endsWith('.' + b))
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
const IMPORTANCE = { key: 2, supporting: 1 }
const VOL = { low: 0, medium: 1, high: 2 }

// ---------------- schemas ----------------
const MODALITY = { type: 'string', enum: ['web', 'papers', 'crawl'] }
const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    restated_question: { type: 'string' },
    scope: { type: 'string', description: 'time window, geography, industry, language, exclusions' },
    sub_questions: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          question: { type: 'string' },
          answer_type: { type: 'string' },
          modalities: { type: 'array', items: MODALITY },
          seed_domains: { type: 'array', items: { type: 'string' } },
          queries: { type: 'array', items: { type: 'string' } },
          settles_it: { type: 'string' },
          priority: { type: 'integer', minimum: 1, maximum: 3 },
        },
        required: ['id', 'question', 'modalities', 'queries'],
      },
    },
    doubt: { type: 'string', description: 'non-empty if the question is unbounded or presupposes a contested fact' },
  },
  required: ['restated_question', 'sub_questions'],
}
const SOURCE_ITEM = {
  type: 'object',
  properties: {
    url: { type: 'string' },
    title: { type: 'string' },
    publisher: { type: 'string' },
    date: { type: 'string', description: 'YYYY-MM-DD or YYYY if known' },
    kind: { type: 'string', enum: ['primary', 'secondary', 'tertiary'] },
    relevance: { type: 'string', description: 'one line; for papers the key result with numbers' },
    score: { type: 'number', minimum: 0, maximum: 1 },
  },
  required: ['url', 'title', 'kind', 'relevance'],
}
const SOURCES_SCHEMA = {
  type: 'object',
  properties: {
    sources: { type: 'array', items: SOURCE_ITEM },
    domains: { type: 'array', items: { type: 'string' }, description: 'up to 3 hostnames (optionally with a path prefix) whose site-wide content is authoritative here' },
    queries_run: { type: 'integer' },
    notes: { type: 'string' },
  },
  required: ['sources'],
}
const CRAWL_SCHEMA = {
  type: 'object',
  properties: {
    sources: { type: 'array', items: SOURCE_ITEM },
    pages_crawled: { type: 'integer' },
    corpus_dirs: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' }, description: 'domains not crawled and why' },
  },
  required: ['sources'],
}
const CLAIMS_SCHEMA = {
  type: 'object',
  properties: {
    claims: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string', description: 'one atomic fact, numbers/units/dates exactly as the source states them' },
          kind: { type: 'string', enum: ['quantitative', 'qualitative', 'definitional', 'causal'] },
          importance: { type: 'string', enum: ['key', 'supporting'] },
          volatility: { type: 'string', enum: ['low', 'medium', 'high'] },
          sources: {
            type: 'array',
            items: {
              type: 'object',
              properties: { url: { type: 'string' }, title: { type: 'string' }, date: { type: 'string' }, quote: { type: 'string', description: 'under 15 words' } },
              required: ['url'],
            },
          },
          caveat: { type: 'string' },
        },
        required: ['claim', 'kind', 'importance', 'sources'],
      },
    },
    answer_sketch: { type: 'string', description: '<= 5 lines: what the read sources say about the sub-question' },
    contradictions: {
      type: 'array',
      items: { type: 'object', properties: { a: { type: 'string' }, b: { type: 'string' }, note: { type: 'string' } }, required: ['a', 'b'] },
    },
    gaps: { type: 'array', items: { type: 'string' } },
    sources_read: { type: 'integer' },
  },
  required: ['claims', 'answer_sketch'],
}
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['supported', 'partially_supported', 'contradicted', 'unverifiable'] },
    corrected_claim: { type: 'string', description: 'for partially_supported or contradicted: the claim as the best evidence states it' },
    evidence: {
      type: 'array',
      items: {
        type: 'object',
        properties: { url: { type: 'string' }, date: { type: 'string' }, quote: { type: 'string' }, supports: { type: 'boolean' } },
        required: ['url', 'supports'],
      },
    },
    stale: { type: 'boolean' },
    notes: { type: 'string' },
  },
  required: ['verdict', 'evidence'],
}
const CRITIC_SCHEMA = {
  type: 'object',
  properties: {
    gaps: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          question: { type: 'string', description: 'a specific, answerable research question' },
          why: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'important', 'minor'] },
          modalities: { type: 'array', items: MODALITY },
          queries: { type: 'array', items: { type: 'string' } },
          seed_domains: { type: 'array', items: { type: 'string' } },
        },
        required: ['question', 'why', 'severity', 'modalities', 'queries'],
      },
    },
    verdict: { type: 'string', enum: ['dry', 'gaps'] },
  },
  required: ['gaps', 'verdict'],
}
const REPORT_SCHEMA = {
  type: 'object',
  properties: {
    report_path: { type: 'string' },
    summary: { type: 'string', description: '<= 8 lines, direct answer first' },
    key_findings: { type: 'array', items: { type: 'string' } },
    open_questions: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'number', minimum: 0, maximum: 1 },
  },
  required: ['report_path', 'summary', 'key_findings', 'confidence'],
}

// ---------------- Plan ----------------
phase('Plan')
const plan = await call(
  `You are the deep-researcher running inside the research-sweep workflow, phase Plan. Do only the decomposition: do not launch research-sweep or any other workflow, do not spawn subagents, and run at most 4 orientation searches (mcp__exa__web_search_exa, mcp__jina__search_web) to learn the vocabulary and locate the primary sources. Write the plan to ${RUN_DIR}/plan.md (mkdir -p first).

Question: ${QUESTION}
Depth: ${DEPTH} (at most ${CFG.maxSubQ} sub-questions; allowed modalities: ${CFG.modalities.join(', ')})
${A.scope ? 'Caller scope: ' + A.scope : 'Caller scope: none given; propose one (time window, geography, industry) in scope.'}
${Array.isArray(A.domains) && A.domains.length ? 'Caller-designated authoritative sites: ' + A.domains.join(', ') : ''}

Decompose into sub-questions that are mutually exclusive and jointly exhaustive for THIS question across definitions, current state, mechanism, quantities, comparisons, risks and open problems (skip axes that do not apply). For each:
- id: SQ1, SQ2, ...; question: specific and answerable; answer_type: number with unit | list | comparison table | mechanism | yes/no with conditions
- modalities: "web" almost always; "papers" only when academic or SSRN literature plausibly answers it; "crawl" only when a specific site (spec, standards body, vendor or project docs, regulator) holds the authoritative text, and then name it in seed_domains as host or host/path-prefix (for example docs.example.org/reference)
- queries: 3-6 starting queries, at least one contrarian ("<X> limitations", "<X> postmortem", "<X> benchmark criticism")
- settles_it: the evidence that would settle it; priority: 1 core to the answer, 2 needed for completeness, 3 context
If the question is unbounded or presupposes a contested fact, say so in doubt and decompose the bounded version you propose in scope.`,
  { label: 'plan', phase: 'Plan', agentType: 'deep-researcher', schema: PLAN_SCHEMA },
)

let restated = QUESTION
let scope = A.scope || ''
let subQs = []
const droppedSq = []
if (plan && Array.isArray(plan.sub_questions) && plan.sub_questions.length) {
  restated = plan.restated_question || QUESTION
  scope = plan.scope || scope
  if (plan.doubt && plan.doubt.trim()) note(`plan doubt (sweep continues on the proposed scope): ${plan.doubt.trim().slice(0, 300)}`)
  const seenIds = new Set()
  const normalized = plan.sub_questions.map((q, i) => {
    let id = String(q.id || 'SQ' + (i + 1)).replace(/[^A-Za-z0-9_.-]/g, '') || 'SQ' + (i + 1)
    if (seenIds.has(id)) id = id + '-' + (i + 1)
    seenIds.add(id)
    const mods = (Array.isArray(q.modalities) ? q.modalities : ['web']).filter(m => CFG.modalities.includes(m))
    if (!mods.includes('web')) mods.unshift('web')
    return { id, question: String(q.question || '').trim(), answer_type: q.answer_type || '', modalities: mods, seed_domains: Array.isArray(q.seed_domains) ? q.seed_domains : [], queries: Array.isArray(q.queries) ? q.queries.slice(0, 8) : [], settles_it: q.settles_it || '', priority: clampInt(q.priority, 1, 3, 2), origin: 'plan' }
  }).filter(q => q.question)
  normalized.sort((x, y) => x.priority - y.priority)
  subQs = normalized.slice(0, CFG.maxSubQ)
  for (const q of normalized.slice(CFG.maxSubQ)) droppedSq.push(q)
  if (droppedSq.length) note(`plan: ${droppedSq.length} lower-priority sub-question(s) over the depth cap were not swept and are reported as gaps: ${droppedSq.map(q => q.id).join(', ')}`)
} else {
  note('plan: decomposition failed; sweeping the whole question as one sub-question')
  subQs = [{ id: 'SQ1', question: QUESTION, answer_type: '', modalities: CFG.modalities.slice(), seed_domains: [], queries: [QUESTION], settles_it: '', priority: 1, origin: 'fallback' }]
}
if (Array.isArray(A.domains) && A.domains.length && CFG.modalities.includes('crawl')) {
  for (const q of subQs) {
    if (q.priority === 1) {
      q.seed_domains = q.seed_domains.concat(A.domains.map(String))
      if (!q.modalities.includes('crawl')) q.modalities.push('crawl')
    }
  }
} else if (Array.isArray(A.domains) && A.domains.length) {
  note(`domains ignored (${A.domains.slice(0, 5).join(', ')}): depth ${DEPTH} has no crawl modality; use depth standard or exhaustive to crawl them`)
}
log(`plan: ${subQs.length} sub-question(s): ${subQs.map(q => q.id + '[' + q.modalities.join('+') + ']').join(', ')}`)

// ---------------- Sweep + Extract (pipeline per sub-question) ----------------
function sqDir(q) { return `${RUN_DIR}/${q.id.toLowerCase()}` }
function sqHeader(q) {
  return `Research question (context): ${restated}
${scope ? 'Scope: ' + scope + '\n' : ''}Sub-question ${q.id}: ${q.question}
${q.answer_type ? 'Answer type: ' + q.answer_type + '\n' : ''}${q.settles_it ? 'What would settle it: ' + q.settles_it + '\n' : ''}Starting queries: ${q.queries.length ? q.queries.map(x => '"' + x + '"').join('; ') : 'derive your own'}`
}

async function searchStage(q) {
  const tasks = []
  const dir = sqDir(q)
  tasks.push(() => call(
    `You are the web-searcher inside the research-sweep workflow (phase Sweep, ${q.id}). Do not spawn subagents or run workflows.
${sqHeader(q)}

1. Run 4-8 query variants: document-shaped neural queries with mcp__exa__web_search_exa ("A production comparison of X and Y at scale found ..."); mcp__exa__web_search_advanced_exa with date or domain filters when recency or a specific publisher matters (check the schema for enum values); keyword and contrarian variants with mcp__jina__search_web (pass an array of up to 5 queries in one call). Fallback: WebSearch.
2. Canonicalize URLs, drop mirrors, SEO aggregators and undated listicles, rerank by relevance to the sub-question (mcp__jina__sort_by_relevance is fine) and keep the top ${CFG.maxSources}, primary sources (official docs, specs, papers, filings, datasets, first-party engineering posts) first.
3. Write the query log (tool | query | filters | hits) and the ranked list to ${dir}/web.md (mkdir -p first).
Return sources (url, title, publisher, date, kind, one-line relevance, score) and domains: up to 3 hosts (with an optional path prefix) whose site-wide content is authoritative for this sub-question and worth crawling; empty if none.`,
    { label: `${q.id}:web`, phase: 'Sweep', agentType: 'web-searcher', schema: SOURCES_SCHEMA },
  ))
  if (q.modalities.includes('papers')) {
    tasks.push(() => call(
      `You are the paper-researcher inside the research-sweep workflow (phase Sweep, ${q.id}). This is a bounded literature pass, not a full review: do not spawn subagents or run workflows.
${sqHeader(q)}

1. Search with mcp__jina__search_arxiv (array of up to 5 queries per call); add mcp__jina__search_ssrn when economics, law, finance or policy is involved; use mcp__exa__web_search_advanced_exa with the research-paper category for venues outside arXiv.
2. Triage by venue, recency, citations and whether the paper measures what the sub-question asks. Read abstract, results and limitations of the best ${DEPTH === 'quick' ? '2-3' : '3-5'} (mcp__jina__read_url on the arXiv abs or html page; mcp__jina__extract_pdf for PDFs).
3. Write ${dir}/papers.md (mkdir -p first): per paper the citation, method, key result with numbers and conditions, limitations.
Return sources: kind "primary" for original papers, relevance = the key result in one line with its numbers. Return an empty list if the literature does not address the sub-question; do not pad with tangential papers.`,
      { label: `${q.id}:papers`, phase: 'Sweep', agentType: 'paper-researcher', schema: SOURCES_SCHEMA },
    ))
  }
  const res = await parallel(tasks)
  const web = res[0] || null
  const papers = q.modalities.includes('papers') ? (res[1] || null) : null
  if (!web) note(`${q.id}: web search failed`)
  if (q.modalities.includes('papers') && !papers) note(`${q.id}: paper search failed`)
  return { web, papers }
}

async function crawlStage(prev, q) {
  if (!prev) return null
  if (!q.modalities.includes('crawl') || CFG.crawlDomains === 0) return Object.assign({}, prev, { crawl: null })
  const cands = []
  for (const d of q.seed_domains.concat((prev.web && Array.isArray(prev.web.domains)) ? prev.web.domains : [])) {
    const hp = hostPath(d)
    if (!hp) continue
    if (cands.some(c => c === hp || hp.startsWith(c + '/'))) continue
    if (!crawlable(hp)) { note(`${q.id}: skipped site-wide crawl of ${hp} (general platform; use a path prefix to crawl it)`); continue }
    cands.push(hp)
  }
  const domains = cands.slice(0, CFG.crawlDomains)
  if (cands.length > domains.length) note(`${q.id}: crawl capped at ${CFG.crawlDomains} domain(s); not crawled: ${cands.slice(CFG.crawlDomains).join(', ')}`)
  if (!domains.length) { note(`${q.id}: crawl requested but no authoritative domain identified`); return Object.assign({}, prev, { crawl: null }) }
  const crawl = await call(
    `You are the web-crawler inside the research-sweep workflow (phase Sweep, ${q.id}). Do not spawn subagents or run workflows.
${sqHeader(q)}

Targets: ${domains.join(', ')}
1. Check credits once with mcp__spider__spider_get_credits; if too low for the limits below, crawl only the first target and say so in skipped.
2. Per target: mcp__spider__spider_crawl scoped to the path prefix most relevant to the sub-question, limit <= ${CFG.crawlPagesPerDomain} pages, depth <= 3, markdown return format. Respect robots.txt; never fill forms or log in. If a site needs JavaScript rendering and returns empty pages, note it in skipped rather than escalating.
3. Save the corpus under ${sqDir(q)}/crawl/<host>/ and write ${sqDir(q)}/crawl/<host>/index.md with url | title | relevant? | one-line note.
Return the 5-15 crawled pages most relevant to the sub-question as sources (kind primary when the site is the authority), pages_crawled and corpus_dirs.`,
    { label: `${q.id}:crawl`, phase: 'Sweep', agentType: 'web-crawler', schema: CRAWL_SCHEMA },
  )
  if (!crawl) note(`${q.id}: crawl failed`)
  return Object.assign({}, prev, { crawl, crawl_domains: domains })
}

async function extractStage(prev, q) {
  if (!prev) return null
  const pool = []
  const seen = new Set()
  const add = (s, via) => {
    if (!s || !s.url) return
    const cu = canonUrl(s.url)
    if (seen.has(cu)) return
    seen.add(cu)
    pool.push(Object.assign({}, s, { url: cu, via }))
  }
  const kindRank = k => ({ primary: 0, secondary: 1, tertiary: 2 })[k] ?? 1
  const ranked = xs => (xs || []).slice().sort((a, b) => (kindRank(a.kind) - kindRank(b.kind)) || ((b.score || 0) - (a.score || 0)))
  for (const s of ranked(prev.papers && prev.papers.sources)) add(s, 'papers')
  for (const s of ranked(prev.crawl && prev.crawl.sources)) add(s, 'crawl')
  for (const s of ranked(prev.web && prev.web.sources)) add(s, 'web')
  pool.sort((a, b) => kindRank(a.kind) - kindRank(b.kind))
  const shown = pool.slice(0, 25)
  if (pool.length > shown.length) note(`${q.id}: ${pool.length - shown.length} lower-ranked candidate source(s) not passed to extraction`)
  if (!shown.length) {
    note(`${q.id}: no sources found by any modality; sub-question becomes a gap`)
    return { sq: q, claims: [], answer_sketch: '', gaps: ['No sources found for: ' + q.question], contradictions: [], sources: [], modalities_run: [] }
  }
  const ex = await call(
    `You are extracting atomic, cited claims for sub-question ${q.id} inside the research-sweep workflow (phase Extract). Never add facts that are not in the sources. Do not spawn subagents or run workflows.
${sqHeader(q)}

Candidate sources (url | title | date | kind | via | relevance):
${shown.map(s => `${s.url} | ${s.title || ''} | ${s.date || '?'} | ${s.kind} | ${s.via} | ${String(s.relevance || '').slice(0, 160)}`).join('\n')}

Saved material (Read it): ${sqDir(q)}/web.md${prev.papers ? ', ' + sqDir(q) + '/papers.md' : ''}${prev.crawl ? ', ' + sqDir(q) + '/crawl/*/index.md (Grep the crawl corpus for the key terms instead of reading it whole)' : ''}

1. Read the best ${CFG.readTop} sources in full (mcp__jina__read_url takes up to 5 URLs per call; use the saved crawl pages when present). Prefer primary sources; include at least one source that disagrees with the majority if one exists.
2. Extract atomic claims that answer the sub-question: one fact per claim; numbers, units, dates and conditions exactly as the source states them, with the source's own qualifiers.
3. Per claim: supporting sources (url, title, date, quote under 15 words), kind, importance (key = the answer to the sub-question depends on it), volatility (high = likely to change within a year: prices, versions, benchmarks, legal status, market share), caveat.
4. contradictions: pairs of claims from different sources that cannot both be true. gaps: what the sub-question needs that no read source answered.
5. Write ${sqDir(q)}/claims.md with the same content as a table.
At most ${CFG.maxClaimsPerSq} claims, key claims first.`,
    { label: `${q.id}:extract`, phase: 'Extract', agentType: 'source-summarizer', schema: CLAIMS_SCHEMA },
  )
  const modalitiesRun = ['web'].concat(prev.papers ? ['papers'] : []).concat(prev.crawl ? ['crawl'] : [])
  if (!ex) {
    note(`${q.id}: extraction failed; its sources are kept but yield no claims`)
    return { sq: q, claims: [], answer_sketch: '', gaps: ['Extraction failed for: ' + q.question], contradictions: [], sources: shown, modalities_run: modalitiesRun }
  }
  const claims = []
  let uncited = 0
  for (const c of (ex.claims || [])) {
    const srcs = (c.sources || []).filter(s => s && s.url).map(s => Object.assign({}, s, { url: canonUrl(s.url) }))
    if (!srcs.length || !String(c.claim || '').trim()) { uncited++; continue }
    claims.push({ sq: [q.id], claim: String(c.claim).trim(), kind: c.kind || 'qualitative', importance: c.importance || 'supporting', volatility: c.volatility || 'medium', caveat: c.caveat || '', sources: srcs })
  }
  if (uncited) note(`${q.id}: dropped ${uncited} claim(s) without a source`)
  return { sq: q, claims, answer_sketch: ex.answer_sketch || '', gaps: ex.gaps || [], contradictions: ex.contradictions || [], sources: shown, modalities_run: modalitiesRun }
}

async function sweep(qs) {
  return pipeline(qs, (q) => searchStage(q), (prev, q) => crawlStage(prev, q), (prev, q) => extractStage(prev, q))
}

// ---------------- ledger (merge + dedup in code) ----------------
const ledger = []
let nextId = 1
function mergeClaims(sqResults) {
  let added = 0, merged = 0
  for (const r of sqResults) {
    if (!r) continue
    for (const c of r.claims) {
      const nums = numbersOf(c.claim)
      const hit = ledger.find(x => numbersOf(x.claim) === nums && jaccard(x.claim, c.claim) >= 0.72)
      if (hit) {
        merged++
        for (const id of c.sq) if (!hit.sq.includes(id)) hit.sq.push(id)
        for (const s of c.sources) if (!hit.sources.some(t => t.url === s.url)) hit.sources.push(s)
        if (IMPORTANCE[c.importance] > IMPORTANCE[hit.importance]) hit.importance = c.importance
        if ((VOL[c.volatility] || 0) > (VOL[hit.volatility] || 0)) hit.volatility = c.volatility
      } else {
        ledger.push(Object.assign({ id: 'C' + (nextId++), status: 'unverified', checks: [] }, c))
        added++
      }
    }
  }
  for (const x of ledger) x.origins = Array.from(new Set(x.sources.map(s => originOf(s.url)))).length
  return { added, merged }
}
const contradictionsAll = []
function contradictionTouches(c) {
  return contradictionsAll.some(k => jaccard(k.a, c.claim) >= 0.6 || jaccard(k.b, c.claim) >= 0.6)
}
function riskScore(c) {
  return (c.importance === 'key' ? 3 : 0) + (c.kind === 'quantitative' ? 2 : 0) + (c.origins < 2 ? 2 : 0) + (c.volatility === 'high' ? 1 : 0) + (contradictionTouches(c) ? 2 : 0)
}

// ---------------- Verify ----------------
const LENSES = [
  { name: 'primary-source', text: 'Trace the claim to its primary or original source (spec, paper, dataset, filing, official docs, first-party benchmark with method) and confirm the exact number or wording and the conditions under which it holds.' },
  { name: 'counter-evidence', text: 'Search specifically for sources that contradict or qualify the claim: newer versions, errata, failed replications, critiques, vendor-neutral benchmarks. Prefer the stronger and newer source when they conflict.' },
]
function combineVerdicts(vs) {
  const live = vs.filter(Boolean)
  if (!live.length) return 'unverified'
  const has = v => live.some(x => x.verdict === v)
  if (has('contradicted') && (has('supported') || has('partially_supported'))) return 'disputed'
  if (has('contradicted')) return 'contradicted'
  if (has('partially_supported')) return 'partially_supported'
  if (has('supported')) return 'supported'
  return 'unverifiable'
}
async function verifyClaims(cands, label) {
  const lenses = LENSES.slice(0, CFG.verifyLenses)
  await pipeline(cands, async (c) => {
    const vs = await parallel(lenses.map(l => () => call(
      `Verify one claim from a research sweep (claim ${c.id}, sub-question ${c.sq.join(', ')}). Do not spawn subagents or run workflows. Run \`date\` first; mark stale=true if the newest supporting evidence is older than the claim's volatility allows (high: 12 months, medium: 3 years).
Research question (context): ${restated}
CLAIM: ${c.claim}
${c.caveat ? 'Caveat noted by the extractor: ' + c.caveat + '\n' : ''}Cited sources: ${c.sources.slice(0, 5).map(s => `${s.url} (${s.date || 'undated'})${s.quote ? ' "' + s.quote + '"' : ''}`).join('; ')}
Lens: ${l.name}. ${l.text}
Verdicts: supported (a primary source says it and the conditions match); partially_supported (true only under narrower conditions or the number is approximate: give corrected_claim); contradicted (a stronger or newer source says otherwise: give corrected_claim); unverifiable (no primary source reachable in about 30 tool calls). Quotes under 15 words. Every evidence item says whether it supports the claim.`,
      { label: `${label}:${c.id}:${l.name}`, phase: 'Verify', agentType: 'fact-checker', schema: VERDICT_SCHEMA },
    )))
    c.checks = vs.map((v, i) => v ? { lens: lenses[i].name, verdict: v.verdict, corrected_claim: v.corrected_claim || '', stale: !!v.stale, evidence: (v.evidence || []).slice(0, 4), notes: v.notes || '' } : { lens: lenses[i].name, verdict: 'failed' })
    c.status = combineVerdicts(vs)
    const corr = vs.filter(Boolean).map(v => v.corrected_claim).filter(Boolean)
    if (corr.length) c.corrected_claim = corr[0]
    c.stale = vs.some(v => v && v.stale)
    for (const v of vs.filter(Boolean)) for (const e of (v.evidence || [])) if (e.url && e.supports && !c.sources.some(s => s.url === canonUrl(e.url))) c.sources.push({ url: canonUrl(e.url), date: e.date || '', quote: e.quote || '', via: 'fact-check' })
    c.origins = Array.from(new Set(c.sources.map(s => originOf(s.url)))).length
    return c.status
  })
}
function pickForVerification(cap, label) {
  const pool = ledger.filter(c => c.status === 'unverified')
  pool.sort((a, b) => (riskScore(b) - riskScore(a)) || (Number(a.id.slice(1)) - Number(b.id.slice(1))))
  const picked = pool.filter(c => c.importance === 'key' || riskScore(c) >= 3).slice(0, cap)
  const left = pool.length - picked.length
  if (left > 0) note(`${label}: ${left} claim(s) left unverified (cap ${cap}; supporting claims with risk score < 3 are not checked); they are labelled unverified in the report`)
  return picked
}

phase('Sweep')
const sqResults = []
const first = await sweep(subQs)
first.forEach((r, i) => {
  if (!r) { note(`${subQs[i].id}: pipeline failed; sub-question becomes a gap`); return }
  sqResults.push(r)
  for (const k of r.contradictions) contradictionsAll.push(Object.assign({ sq: r.sq.id }, k))
})
const m1 = mergeClaims(sqResults)
log(`ledger: ${ledger.length} claims (${m1.merged} duplicate(s) merged across sub-questions), ${contradictionsAll.length} contradiction(s) reported`)

phase('Verify')
if (!ledger.length) note('no claims extracted; verification skipped')
else if (CFG.verifyCap === 0) note('verifyCap=0: verification disabled; every claim is reported as unverified')
else await verifyClaims(pickForVerification(CFG.verifyCap, 'verify'), 'v0')

// ---------------- Critic loop (until dry) ----------------
phase('Critic')
const seenGaps = []
const residualGaps = droppedSq.map(q => ({ question: q.question, why: 'sub-question over the depth cap (priority ' + q.priority + ')', severity: 'minor', source: 'plan-cap' }))
let criticRoundsRun = 0
let dry = false
function statusSummary() {
  return sqResults.map(r => {
    const cs = ledger.filter(c => c.sq.includes(r.sq.id))
    const by = {}
    for (const c of cs) by[c.status] = (by[c.status] || 0) + 1
    const keySupported = cs.filter(c => c.importance === 'key' && (c.status === 'supported' || c.status === 'partially_supported')).length
    return `${r.sq.id} [${r.modalities_run.join('+')}] ${r.sq.question}\n  claims=${cs.length} key_supported=${keySupported} status=${JSON.stringify(by)} single-origin key=${cs.filter(c => c.importance === 'key' && c.origins < 2).length}\n  sketch: ${String(r.answer_sketch).replace(/\s+/g, ' ').slice(0, 300)}\n  extractor gaps: ${(r.gaps || []).slice(0, 4).join(' | ') || 'none'}`
  }).join('\n')
}
for (let round = 1; round <= CFG.criticRounds; round++) {
  if (lowBudget(150000)) { note(`critic round ${round}: skipped, token budget nearly exhausted`); break }
  criticRoundsRun = round
  const contradicted = ledger.filter(c => c.status === 'contradicted' || c.status === 'disputed').map(c => `${c.id}: ${c.claim} -> ${c.status}${c.corrected_claim ? ' (best evidence: ' + c.corrected_claim + ')' : ''}`)
  const crit = await call(
    `You are the completeness critic inside the research-sweep workflow (phase Critic, round ${round} of at most ${CFG.criticRounds}). You judge coverage; you do not research. Do not spawn subagents or run workflows.
Research question: ${restated}
${scope ? 'Scope: ' + scope : ''}
Depth: ${DEPTH}. Modalities available: ${CFG.modalities.join(', ')}.

COVERAGE BY SUB-QUESTION:
${statusSummary()}

CONTRADICTED OR DISPUTED CLAIMS:
${contradicted.join('\n') || 'none'}

GAPS ALREADY RAISED (do not repeat): ${seenGaps.map(g => g.question).join(' | ') || 'none'}

Find what is missing for a decision-grade answer: a sub-question without a supported key claim; a contradicted claim with no replacement; a modality not run where it matters (no papers on an academic topic, no primary docs on a spec question); a key claim resting on a single origin; a missing time frame, geography or population; missing counter-evidence or failure cases.
Return each gap as a new, specific, answerable research question (never "more research on X"), with why it matters, severity (critical: the answer could flip; important: the answer is incomplete; minor: nice to have), modalities, 2-4 queries and seed_domains when a specific site is authoritative. verdict "dry" when nothing critical or important remains.`,
    { label: `critic:r${round}`, phase: 'Critic', agentType: 'quality-control', schema: CRITIC_SCHEMA },
  )
  if (!crit) { note(`critic round ${round}: critic failed; loop stopped`); break }
  const all = crit.gaps || []
  for (const g of all.filter(g => g.severity === 'minor')) residualGaps.push({ question: g.question, why: g.why, severity: 'minor', source: 'critic' })
  const fresh = all.filter(g => g.severity !== 'minor')
    .filter(g => !seenGaps.some(s => jaccard(s.question, g.question) >= 0.6))
    .filter(g => !subQs.some(q => jaccard(q.question, g.question) >= 0.6))
  for (const g of all.filter(g => g.severity !== 'minor')) if (!fresh.includes(g)) note(`critic round ${round}: repeated gap ignored: ${String(g.question).slice(0, 80)}`)
  if (!fresh.length || (crit.verdict === 'dry' && !fresh.some(g => g.severity === 'critical'))) {
    dry = true
    log(`critic round ${round}: dry (no new critical or important gap)`)
    for (const g of fresh) residualGaps.push({ question: g.question, why: g.why, severity: g.severity, source: 'critic-dry' })
    break
  }
  fresh.sort((a, b) => (a.severity === 'critical' ? 0 : 1) - (b.severity === 'critical' ? 0 : 1))
  const take = fresh.slice(0, CFG.gapsPerRound)
  for (const g of fresh) seenGaps.push(g)
  for (const g of fresh.slice(CFG.gapsPerRound)) residualGaps.push({ question: g.question, why: g.why, severity: g.severity, source: 'critic-cap' })
  if (fresh.length > take.length) note(`critic round ${round}: ${fresh.length - take.length} gap(s) over the per-round cap (${CFG.gapsPerRound}) reported, not researched`)
  const newQs = take.map((g, i) => {
    const mods = (g.modalities || ['web']).filter(m => CFG.modalities.includes(m))
    if (!mods.includes('web')) mods.unshift('web')
    return { id: `G${round}.${i + 1}`, question: g.question, answer_type: '', modalities: mods, seed_domains: g.seed_domains || [], queries: (g.queries || []).slice(0, 6), settles_it: g.why, priority: g.severity === 'critical' ? 1 : 2, origin: 'critic' }
  })
  log(`critic round ${round}: researching ${newQs.length} gap(s): ${newQs.map(q => q.id).join(', ')}`)
  subQs.push(...newQs)
  const res = await sweep(newQs)
  const fresh2 = []
  res.forEach((r, i) => {
    if (!r) { note(`${newQs[i].id}: pipeline failed`); residualGaps.push({ question: newQs[i].question, why: 'gap sweep failed', severity: 'important', source: 'critic' }); return }
    sqResults.push(r)
    fresh2.push(r)
    for (const k of r.contradictions) contradictionsAll.push(Object.assign({ sq: r.sq.id }, k))
  })
  const m = mergeClaims(fresh2)
  log(`critic round ${round}: +${m.added} claims (${m.merged} merged into existing)`)
  const capR = Math.max(2, Math.ceil(CFG.verifyCap / 3))
  if (CFG.verifyCap > 0) await verifyClaims(pickForVerification(capR, `verify:r${round}`), `v${round}`)
}
if (!dry && CFG.criticRounds > 0 && criticRoundsRun === CFG.criticRounds) note(`critic loop hit the depth cap (${CFG.criticRounds} rounds) before running dry; remaining gaps are listed`)
for (const r of sqResults) for (const g of (r.gaps || [])) {
  const resolved = ledger.some(c => (c.status === 'supported' || c.status === 'partially_supported') && jaccard(c.claim, g) >= 0.5)
  if (!resolved && !residualGaps.some(x => jaccard(x.question, g) >= 0.6)) residualGaps.push({ question: g, why: 'reported by the extractor for ' + r.sq.id, severity: 'unknown', source: 'extractor' })
}

// ---------------- Synthesize ----------------
phase('Synthesize')
const counts = {}
for (const c of ledger) counts[c.status] = (counts[c.status] || 0) + 1
const compact = c => ({ id: c.id, sq: c.sq, claim: c.claim, status: c.status, corrected: c.corrected_claim || undefined, stale: c.stale || undefined, importance: c.importance, volatility: c.volatility, origins: c.origins, sources: c.sources.slice(0, 3).map(s => (s.date ? s.date + ' ' : '') + s.url) })
let ledgerOut = ledger.map(compact)
let ledgerText = JSON.stringify(ledgerOut)
if (ledgerText.length > 70000) {
  const keyOnly = ledger.filter(c => c.importance === 'key' || c.status !== 'unverified').map(compact)
  note(`ledger too large for one prompt (${ledgerText.length} chars); passing ${keyOnly.length} key or verified claims inline, the rest are in ${RUN_DIR}/<sq>/claims.md`)
  ledgerText = JSON.stringify(keyOnly).slice(0, 70000)
}
const stats = {
  depth: DEPTH,
  sub_questions: subQs.length,
  sub_questions_from_critic: subQs.filter(q => q.origin === 'critic').length,
  sources_considered: sqResults.reduce((t, r) => t + r.sources.length, 0),
  claims: ledger.length,
  status_counts: counts,
  contradictions_reported: contradictionsAll.length,
  critic_rounds: criticRoundsRun,
  ran_dry: dry,
  verify_lenses: CFG.verifyLenses,
}
const report = await call(
  `You are the deep-researcher running inside the research-sweep workflow, phase Synthesize. Do not launch research-sweep or any other workflow and do not start a new sweep; at most 6 lookups to fix a wording or a date. Sweeping, extraction and fact-checking are done; the ledger below is authoritative for claim status.

Write (mkdir -p as needed):
- ${RUN_DIR}/claims.md: C# | claim | SQ | status | origins | sources
- ${RUN_DIR}/sources.md: S# | title | publisher | URL | date | kind (number every source you cite)
- ${OUT_FILE}: the report.
Report structure: title; Answer (<= 10 lines, the direct answer first, with overall confidence and what it rests on); Findings per sub-question (numbers with units and dates; cite as [S#]); Contradictions and how they resolve; Gaps and unverified claims; Methodology (modalities run per sub-question, counts of sources, claims and verification outcomes, critic rounds, every cap that dropped work); References (URL, publication date, access date from \`date\`).
Rules: a contradicted claim never appears as fact (state the corrected claim if one was verified); a disputed claim shows both sides; unverified and unverifiable claims are labelled; key claims with origins=1 are flagged "single source"; stale=true claims are flagged with their date; quotes under 15 words; no claim without a source.

Question: ${restated}
${scope ? 'Scope: ' + scope : ''}
Per-sub-question notes: ${RUN_DIR}/<sq-id lowercased>/web.md, papers.md, claims.md, crawl/*/index.md
Sub-questions: ${JSON.stringify(sqResults.map(r => ({ id: r.sq.id, question: r.sq.question, modalities_run: r.modalities_run, sketch: String(r.answer_sketch).slice(0, 400) })))}
Stats: ${JSON.stringify(stats)}
Contradictions reported by extractors: ${JSON.stringify(contradictionsAll.slice(0, 40))}
Residual gaps: ${JSON.stringify(residualGaps.slice(0, 40))}
Workflow notes (caps and failures): ${JSON.stringify(notes.slice(0, 40))}
LEDGER: ${ledgerText}`,
  { label: 'synthesize', phase: 'Synthesize', agentType: 'deep-researcher', schema: REPORT_SCHEMA },
)
if (!report) note(`synthesis failed; no report written to ${OUT_FILE}. The ledger is returned; per-sub-question notes are under ${RUN_DIR}/`)

return {
  started: true,
  completed: !!report,
  question: restated,
  scope,
  report_path: report ? (report.report_path || OUT_FILE) : null,
  summary: report ? report.summary : 'Synthesis failed; see claims and run_dir.',
  key_findings: report ? report.key_findings : [],
  open_questions: report ? (report.open_questions || []) : [],
  confidence: report ? report.confidence : null,
  // with a report on disk, return digests only; the full ledger is in claims.md
  claims: report ? undefined : ledgerOut,
  claims_path: report ? `${RUN_DIR}/claims.md` : null,
  flagged_claims: report ? ledger.filter(c => c.status === 'contradicted' || c.status === 'disputed' || (c.importance === 'key' && c.origins < 2)).slice(0, 10).map(c => ({ id: c.id, sq: c.sq, status: c.status, single_origin: c.origins < 2 || undefined, claim: String(c.claim).slice(0, 200) })) : undefined,
  gaps: report ? residualGaps.filter(g => g.severity !== 'minor').map(g => g.question).slice(0, 10) : residualGaps,
  contradictions: report ? contradictionsAll.length : contradictionsAll,
  sub_questions: subQs.map(q => ({ id: q.id, question: q.question, origin: q.origin, modalities: q.modalities })),
  stats,
  run_dir: RUN_DIR,
  notes,
}
