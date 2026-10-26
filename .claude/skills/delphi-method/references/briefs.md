# Delphi briefs

Copy, fill the angle-bracket fields, and send one brief per panelist per round. Every brief is
self-contained: the panelist sees neither your conversation nor other panelists.

## Round-1 panelist brief

```text
You are panelist <P-id> on an anonymous Delphi panel. Other panelists exist; you will not see who
they are. Do not spawn subagents. Do not read other files in <round-dir>.

QUESTION
<question spec, verbatim, including unit, resolution, horizon, conditions>

CONTEXT (read these; nothing else is assumed known)
<path 1>
<path 2>

YOUR ASSIGNED METHOD: <method name>
<one-paragraph method instruction from SKILL.md section 2>
<if research allowed: You may use WebSearch / mcp__exa__web_search_exa, at most 12 searches; cite URL + date.>
<if not: Do not search the web; reason from the context files and your knowledge.>

ANSWER
Write exactly one JSON object to <round-dir>/<P-id>.json with keys:
  panelist, p10, p50, p90 (numbers in <unit>; p10 <= p50 <= p90),
  confidence (low|medium|high), method,
  arguments: list of {id: a1.., direction: up|down|neutral, text (<= 40 words), evidence (path:line, URL, or "reasoning")},
  assumptions: list of strings,
  would_change_if: one sentence naming an observable.
Your p10 and p90 mean: you would be surprised (1 in 10) to see the truth below p10 or above p90.
Return only the file path and your p50.
```

Probability questions replace p10/p50/p90 with `p50` = probability of the event (0 < p < 1), and
add `base_rate` when the method is outside view. Ranking questions use `ranking: [best..worst]`
covering every option exactly once, no ties.

## Round-r panelist brief (r >= 2)

```text
You are panelist <P-id> on the same anonymous Delphi panel, round <r>. Do not spawn subagents.

QUESTION (unchanged)
<spec>

YOUR PREVIOUS ANSWER
<their previous JSON>

FEEDBACK FROM ROUND <r-1> (all panelists anonymised)
Arguments pushing UP:
  U1 (<k> panelists, evidence: yes/no) <text>
  ...
Arguments pushing DOWN:
  D1 (<k> panelists, evidence: yes/no) <text>
  ...
Rationales from panelists outside the middle half:
  - "<verbatim, <= 80 words>"
  ...
New evidence obtained by the chair:
  - <claim> : <verdict> (<source or command>, grade A/B)
Distribution: median <m>, middle half <q1>-<q3>, range <min>-<max>, values <sorted list>.

RULES
1. For p10, p50, p90 state keep or revise.
2. If you revise, cite the argument ids (U1, D2, ...) or new evidence that caused it. The group
   median is not a reason.
3. If your previous p50 was outside <q1>-<q3> and you keep it, rebut the strongest opposing
   argument in <= 80 words.
4. Add new arguments or evidence if you have them (same format as round 1).

Write the same JSON shape as round 1 plus: decision {p10: keep|revise, p50: ..., p90: ...},
cited: [argument ids], rebuttal (if rule 3 applies), to <round-dir>/<P-id>.json.
Return only the path and your p50.
```

## Crux brief (sent to the dissenter and two majority panelists)

```text
Panel question: <spec>. Current values: yours <x>; the other view <y>.
In <= 60 words: what single observation, measurement or source would move you to <y>?
Name it precisely enough that someone could check it today (file, query, command, document).
```

If the named observables match, dispatch the check (fact-checker, tester, quick-researcher, or run
it yourself) and include the verdict in the crux round's feedback packet as chair evidence.

## Argument-clustering brief (source-summarizer, for large panels)

```text
Input: <round-dir>/*.json (arguments arrays only).
Task: merge arguments that make the same point into clusters. Do not add, strengthen or soften any
argument. For each cluster: id (U1.. for up, D1.. for down, N1.. neutral), one-sentence text in the
panelists' words, count of panelists, evidence present yes/no (yes only if any member cited a path,
URL or measured result). Write JSON to <run-dir>/clusters-r<r>.json (never inside a round
directory) and return a one-line summary (cluster count) and the path.
```

source-summarizer is LOW tier in config/models.json; pass no model/effort on the call. Spot-check
three clusters against the raw files before using them.
