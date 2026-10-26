# Shard recipes

Commands and snippets for enumerating a universe, sizing and planning shards. Run from the repo
root. Everything here is read-only except writing shard lists under `.stack/out/`.

## 1. Enumerate the universe

### Code

```bash
# Tracked source files, excluding tests, vendored and generated code
git ls-files '*.go' ':!:*_test.go' ':!:vendor/*' ':!:*.pb.go' | wc -l

# LOC per top-two-level directory (cohesion groups), largest first
git ls-files -z '*.rs' | xargs -0 wc -l \
  | awk '$2!="total"{n=split($2,p,"/"); d=(n>2)?p[1]"/"p[2]:p[1]; s[d]+=$1} END{for(d in s) print s[d], d}' \
  | sort -rn | head -40

# Hotspots: churn over 12 months (files changed most often); intersect with the LOC list
git log --since=12.months --name-only --format= | grep -v '^$' | sort | uniq -c | sort -rn | head -30
```

Exclude generated and minified files explicitly (`*.min.js`, `*.pb.go`, `*_generated.*`, lockfiles);
they inflate LOC and are rarely where the defect is. Say in the ledger what was excluded.

### Sources

- Sub-questions x modalities: one shard per (sub-question, modality) where modality is
  web (`web-searcher`, Exa/Jina search), papers (`paper-researcher`, `mcp__jina__search_arxiv`),
  crawl (`web-crawler`, Spider over 1-3 key domains).
- Known site: `mcp__spider__spider_links` (or a shallow `spider_crawl` with a small limit) to list
  URLs, then shard the URL list by path prefix, 8-15 pages per shard.
- Batch-friendly reads: `mcp__jina__read_url` and `mcp__jina__search_web` accept up to 5 URLs or
  queries per call, so a 12-URL shard is 3 calls, not 12.

### Hypotheses

Take them from the debugger's hypothesis log or the brief. Each shard gets one hypothesis plus a
discriminating test ("if H, then running X shows Y; if not H, Z"). Hypotheses without a test are
not shardable; send them back for refinement.

### Parameter grids

```python
import itertools
grid = {"batch": [32, 64, 128, 256], "threads": [1, 2, 4, 8], "prefetch": [0, 1]}
points = [dict(zip(grid, v)) for v in itertools.product(*grid.values())]   # 32 points
```

Coarse-to-fine: run a coarse grid (2-3 values per axis), keep the top quartile, refine around it.
Successive halving: start n configs with budget b each, keep the best n/2 with 2b, repeat;
total budget about `n * b * log2(n)`.

### Time windows

Half-open windows `[start, end)` avoid double counting at boundaries:

```bash
git rev-list --count --since=2026-01-01 --until=2026-04-01 HEAD    # size of a quarter
git log --since=2026-01-01 --until=2026-04-01 --format='%h %s' > .stack/out/swarm-coordinator/q1.txt
```

## 2. Plan shards with shard_plan.py

```bash
mkdir -p .stack/out/swarm-coordinator/cc-audit-shards
git ls-files -z '*.go' ':!:*_test.go' ':!:vendor/*' | xargs -0 wc -l \
  | python3 .claude/skills/swarm-execution/scripts/shard_plan.py \
      --capacity 20000 --group-depth 2 --list-dir .stack/out/swarm-coordinator/cc-audit-shards \
  > .stack/out/swarm-coordinator/cc-audit-plan.json
```

Output fields: `universe` (files, total size), `balance` (`max_over_mean`, target under 1.5),
`shards[]` with `id`, `brief` (a SCOPE line), `units`, `size`, `scope`, `oversize`.
Pass `shards[].{id, brief}` to `/swarm-run` as `args.shards`; put the shared goal, task and item
format into `args.task`. An `oversize` shard is a single file above capacity: give it to an
ADVANCED-tier agent (e.g. `reviewer`, `security-auditor` or the language expert) or tell the worker to
review symbol by symbol.

Tuning: `--group-depth 1` for small repos or flat layouts, `3` for monorepos with
`services/<name>/<module>`. If `max_over_mean` is above 1.5, lower `--capacity` by 20% and re-run.

## 3. Turn budgets by worker type

Expected tool calls should stay under about 0.6 x `maxTurns` (initial values from `config/models.json`;
the learner may have tuned the frontmatter, so read the agent file if precision matters).

| Worker | maxTurns (config/models.json) | Comfortable calls per shard | Shard guidance |
|--------|-------------------------------|-----------------------------|----------------|
| `reviewer` | 360 | ~216 | 5k LOC deep, 15-30k targeted |
| `security-auditor` | 360 | ~216 | one trust boundary or service per shard |
| `code-quality-analyst` | 270 | ~162 | one package; tools first (linters, complexity) |
| `debugger` | 480 | ~288 | one hypothesis |
| `tester` | 450 | ~270 | one module's test plan or one grid slice |
| `code-optimizer` | 450 | ~270 | one hot path |
| `web-searcher` | 150 | ~90 | one sub-question, 3-6 query variants |
| `web-scraper` | 240 | ~144 | 8-15 URLs |
| `web-crawler` | 360 | ~216 | one domain or path prefix |
| `paper-researcher` | 360 | ~216 | 5-10 papers |
| `fact-checker` | 180 | ~108 | 6-12 claims |
| `source-summarizer` | 105 | ~63 | 3-6 sources |
| `file-summarizer` | 120 | ~72 | one large file or log |

Shard guidance is bounded by context (read budget), not only by turns: more turns do not justify
larger shards.

## 4. URL canonicalization (dedup key for sources)

```python
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

DROP = {"gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src"}

def canon(url: str) -> str:
    s = urlsplit(url.strip())
    host = s.hostname.lower() if s.hostname else ""
    if host.startswith("www."):
        host = host[4:]
    port = "" if s.port in (None, 80, 443) else ":%d" % s.port
    q = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in DROP]
    path = s.path.rstrip("/") or "/"
    return urlunsplit(("https", host + port, path, urlencode(sorted(q)), ""))
```

Then special-case: arXiv `abs/2401.01234v3` and `pdf/2401.01234v3` both map to `arxiv:2401.01234`;
DOIs map to `doi:<lowercase doi>`.

## 5. Ledger as JSON (when a script or workflow consumes it)

```json
{ "swarm": "go-leaks", "universe": {"unit": "file", "count": 1550},
  "shards": [
    {"id": "s07", "scope": "internal/sched/**", "units": 96, "agent": "go-expert", "model": "sonnet",
     "attempt": 1, "status": "split", "covered": 9, "items": 1, "children": ["s07a", "s07b"],
     "file": ".stack/out/go-expert/go-leaks/s07.md", "note": "maxTurns"} ],
  "dropped": [{"scope": "third_party/**", "units": 310, "reason": "vendored, excluded by brief"}],
  "coverage": {"covered": 1240, "of": 1550} }
```

Leaf shards are those without `children`. Check: `sum(units of leaves) + sum(dropped units) == count`.
