# Quick research: worked examples

Each example shows the scope card, the calls actually issued, and the returned Result. URLs are the
real primary locations; dates marked `<...>` are filled from what the source shows at read time.

## 1. Stable fact (2 searches, 1 read)

Question: "Which Python release added `tomllib` to the standard library?"

```
Q: First CPython release whose stdlib includes tomllib
Answer shape: version
As-of: 2026-10-19; volatility: stable
Owner: python.org docs / PEP index
Done when: 1 primary source states it directly
```

Calls (same message):
- `mcp__exa__web_search_advanced_exa {query: "Python What's New page introducing the tomllib module", includeDomains: ["docs.python.org", "peps.python.org"], numResults: 5}`
- `mcp__jina__search_web {query: ["tomllib python version added", "PEP 680 tomllib"], num: 5}`

Then: `mcp__jina__read_url {url: ["https://docs.python.org/3/whatsnew/3.11.html", "https://peps.python.org/pep-0680/"], question: "Which version adds tomllib?", topk: 2}`

Result: "Python 3.11 added `tomllib` (read-only TOML parsing), specified by PEP 680 [1][2]." Confidence
0.96: two primary sources, stable fact.

## 2. Small comparison (2 searches, 2 pages in 1 read)

Question: "Does PostgreSQL 17 or 18 add native support for virtual generated columns?"

```
Answer shape: yes/no per version + condition
Owner: postgresql.org release notes and docs
Done when: release notes of the version that introduced it
```

Calls:
1. Exa advanced, `includeDomains: ["postgresql.org"]`, query "PostgreSQL release notes introducing virtual generated columns".
2. Jina batch: `["postgresql virtual generated columns release", "postgres 18 virtual generated column default"]`.
3. Read the release notes page found plus the `CREATE TABLE` docs page for the version, `question: "virtual generated column"`.

Result pattern: state which version introduced it and whether it became the default, each with [n]
to the release notes and the versioned docs page. If the release notes and a blog disagree, the
release notes win; note the blog only if the caller would otherwise meet the wrong claim.

## 3. Volatile fact (date-bounded)

Question: "What is the current Active LTS line of Node.js?"

```
As-of: 2026-10-19; volatility: high (changes every October)
Owner: nodejs.org release schedule; github.com/nodejs/Release
Done when: the official schedule page read today
```

Calls: Jina `search_web {query: ["Node.js release schedule active LTS"], tbs: "qdr:m"}` +
`read_url {url: ["https://nodejs.org/en/about/previous-releases", "https://github.com/nodejs/Release"], question: "Which release line is Active LTS?"}`.

Result must carry "as of 2026-10-19" and the date the page shows. Lines transition in late October:
if the read date is within two weeks of a scheduled transition, say so and give both lines' status.

## 4. Escalation: no direct answer

Question: "What fraction of Fortune 500 companies run Kubernetes in production?"

After 12 searches: vendor surveys with self-selected samples, no census. Return:

```markdown
## Result
Status: partial
No source measures this directly. Available figures come from vendor surveys with self-selected
respondents and do not map to the Fortune 500 [1][2].

## Open doubts
- [factual|med] No direct measure of Kubernetes adoption among Fortune 500 firms - any number given would be a vendor survey proxy - resolve: deep research triangulating job postings, case studies and survey methodology - route: deep-researcher

## Confidence
0.80 (high) that no direct source exists in the first 12 searches; 0.0 basis for any specific fraction.
```

## 5. Conflict between credible sources

Question: "What is the default `max_connections` in PostgreSQL?"

Docs say 100 (typical default, may be lower if kernel settings prevent it at initdb); a managed
cloud provider page shows a different number. These do not conflict once scope is explicit: the
community default versus a provider's tuned default. Resolve by scoping the answer ("community
PostgreSQL: 100 [1]; managed services set their own, e.g. based on instance memory [2]") rather than
escalating. Escalate only when sources disagree about the same scope.

Checklist for "is this a real conflict?":
1. Same version or release?
2. Same platform or edition (community vs managed vs enterprise)?
3. Same definition of the quantity (median vs mean, list price vs effective)?
4. Same date window?
If all four match and the values differ, it is a real conflict: escalate.
