---
name: quick-research
description: "Fast research protocol for one focused question - scope it, run 1-4 targeted Exa/Jina searches, read the 2-3 best sources, and answer in at most 200 words with inline citations and a calibrated confidence, plus explicit escalation triggers to deep research. Load for quick lookups, single-fact checks, version or date questions, and deciding whether a question is really quick."
when_to_use: "A question with one answer shape (a fact, number, date, version, yes/no, short list or definition) that 2-3 good sources can settle; also when general chat needs one fact checked."
---

# Quick research

Budget: **at most 12 search calls, 9 source reads, about 24 tool calls, 200 words of answer.**
quick-researcher is a MEDIUM-tier, low-effort agent (config/models.json); the budget above is the
limit, not its maxTurns. A run that needs more is not quick: escalate (section 6) instead of
stretching the budget.

## 1. Gate: is this actually quick?

| Signal in the question | Route |
|---|---|
| One entity, one attribute (date, version, number, owner, definition) | quick |
| Yes/no about a documented behaviour | quick (find the doc that says it) |
| Compare 2-3 named items on 1-3 stated criteria | quick, use all 12 searches |
| "Why", "state of the art", "landscape", "all X", "best X for Y" | deep-researcher |
| Contested topic, sources known to disagree, or high stakes (health, legal, money, safety) | deep-researcher, or fact-checker on each claim |
| Needs 3+ independent sub-answers | deep-researcher (the research-sweep workflow at depth quick only if you are the main thread, i.e. no `<stack-context>` header; a subagent returns it as an Open doubt) |
| Answer lives behind JS interaction (dashboards, filters) | browser-operator |
| Academic: "what does paper X report", "who introduced Y" | quick if one paper; paper-researcher if a comparison |

If you are a caller deciding where to send a question, the same table applies.

## 2. Scope card (write it before searching)

```
Q: <the question, sharpened>
Answer shape: <date | number+unit | version | yes/no + condition | name | list of <=5>
As-of: <today's date; is the fact volatile? (versions, prices, roles, laws, rankings = yes)>
Owner of the fact: <who would publish it first: vendor docs, registry, regulator, paper, filing>
Done when: <1 primary source states it directly | 2 independent sources agree>
```

The "owner of the fact" line drives search 1. For a release date the owner is the project's release
notes or package registry; for a statute, the official journal; for a paper's result, the paper.

## 3. Search plan (1-4 calls)

Issue calls 1 and 2 in the same message.

| Call | Tool | Purpose | Example (question: which Python release added `tomllib`?) |
|---|---|---|---|
| 1 | `mcp__exa__web_search_advanced_exa` with `includeDomains` = owner domains | primary-pinned | `{query: "Python docs page announcing the tomllib module", includeDomains: ["docs.python.org","peps.python.org"], numResults: 5}` |
| 2 | `mcp__jina__search_web` with 2-3 variants in one array | keyword coverage | `{query: ["tomllib python version added", "PEP 680 tomllib"], num: 5}` |
| 3 (if needed) | Exa `web_search_exa` neural description | when 1-2 missed | `"An article explaining when TOML parsing was added to the Python standard library"` |
| 4 (if needed) | date-bounded or contrarian | volatility or conflict check | `startPublishedDate: <1 year ago>` or `"tomllib" removed OR deprecated` |

Swap tools by question type (full chooser: web-search-tools):
- paper facts: `mcp__jina__search_arxiv`;
- recent news: Exa advanced `category: "news"` + `startPublishedDate`;
- code or repos: Exa advanced `category: "github"`;
- no MCP available: `WebSearch` with `allowed_domains`.

**Stop searching** as soon as the "done when" condition is reachable from what you have.

## 4. Pick and read 2-3 sources

Score each candidate from titles and snippets (30 seconds, no reading yet):

| Signal | Points |
|---|---|
| Primary source (the owner of the fact) | +3 |
| Snippet already contains the answer | +1 |
| Date fits the as-of requirement | +1 |
| Recognised authority for the topic (standards body, maintainer, regulator, peer-reviewed venue) | +1 |
| Aggregator, SEO listicle, undated, or AI-generated filler | -2 |
| Vendor talking about a competitor or itself on a contested claim | -1 (keep, label conflict of interest) |

Read the top 2-3 in ONE call:
- `mcp__jina__read_url {url: [u1, u2, u3], question: "<Q>", topk: 2}` returns only answering
  passages: cheapest and usually enough.
- Full text only for the source you will quote: `read_url {url: [u1]}` or
  `mcp__exa__web_fetch_exa {urls: [u1], maxCharacters: 12000}`.
- Missing date: `mcp__jina__guess_datetime_url {url}`.

From each source capture: the sentence that answers (quote under 15 words), the publish or update
date, the publisher, the URL, today's access date.

## 5. Answer (at most 200 words)

Inside output-contract's `## Result`:

```markdown
## Result
Status: done
**Answer:** <one sentence that answers the question directly>
<1-4 sentences or bullets of necessary qualification, each factual claim tagged [n]>

## Evidence
[1] <Publisher>. "<Title>." <published YYYY-MM-DD>. <URL> (accessed YYYY-MM-DD) - "<quote under 15 words>"
[2] ...
Searches: 2 (exa advanced, jina batch of 2); reads: 2.

## Files
none

## Open doubts
none

## Confidence
0.95 (very high) - two primary sources state it directly; stable fact.
```

Word count covers Result only. Cut adjectives, history and background before you cut qualifications
that change the answer ("only on Linux", "since v2.3, default off").

### Confidence for quick answers

| Evidence | Value |
|---|---|
| Primary owner states it directly and current, plus a second independent source or the fact is stable | 0.90-0.97 |
| Primary states it but is 1+ volatility windows old, or only one good secondary source | 0.70-0.85 |
| Indirect inference from sources, or only weak sources | 0.45-0.65 (normally escalate instead) |
| Credible sources conflict | do not answer; escalate |

Volatility windows: prices, versions, availability, rankings: weeks; APIs, policies, laws, people in
roles: months; best practices: 1-2 years; history, mathematics, physical constants: stable.

## 6. Escalation triggers

| Trigger | Action |
|---|---|
| Two credible sources disagree on the core fact | Stop. Result `Status: partial` with both claims and citations; Open doubt routed to fact-checker (one claim) or deep-researcher (a pattern) |
| 12 searches done and no source states the answer directly | `partial`; Open doubt for deep-researcher with the queries already tried |
| The question splits into 3+ independent sub-questions | Return the decomposition with `Status: partial`; Open doubt routed to deep-researcher, or for the main thread `Workflow name=research-sweep args={"question": "<q>", "depth": "quick"}` |
| The only source is behind JS interaction | Open doubt routed to browser-operator (no logins) |
| High-stakes domain | Answer only what the primary source says; add "not professional advice"; recommend fact-checker on each number |
| Only sources older than the volatility window | Answer with "as of <source date>" and cap confidence at 0.7 |

Spawning: quick research normally does not spawn. If you hold `remaining_depth` of 1 or more, the
header shows `budget="ok"` or `"soft"`, and the caller's brief allows it, a single fact-checker call
(with `run_in_background: false`) for one contested number is acceptable; at `budget="hard"` and
otherwise return the Open doubt and let the caller route it (doubt-escalation, section 4 brief).

## 7. Anti-patterns

- Answering from memory when the brief asked for research. Memory may guide queries, never cite it.
- Citing a search snippet without reading the page: snippets truncate and lose qualifiers.
- Citing an aggregator that cites the primary: follow the link, cite the primary.
- Spending searches on near-synonyms of one query instead of different angles (section 3).
- A fourth search "just to be sure" after the done condition is met.
- Quotes of 15 words or more; paraphrase instead.
- Padding the answer with background the caller did not ask for.

Worked examples (fact, comparison, volatile fact, escalation, conflict):
[quick research examples](references/examples.md).
