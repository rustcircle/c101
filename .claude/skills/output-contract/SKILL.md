---
name: output-contract
description: "Universal return format for every agent in this stack (Result, Evidence, Files, Open doubts, Confidence), confidence calibration, the file-offloading rule for long outputs with line-anchored summaries, and milestone logging (bin/stack milestone) for the events relayed to the user. Preloaded into every agent; apply it to every reply you return."
when_to_use: "Before writing any final reply to a caller, whenever output would exceed about 60 lines or 3k characters, when reading a child agent's offloaded output file, and when a plan, gate, decision, failure, blocker, user-needed action or deliverable occurs mid-run."
---

# Output contract

Every reply you return to a caller (parent agent, saved workflow, or the user at depth 0) ends with
exactly these five sections, in this order, with these headings. Callers parse them; a missing or
renamed heading is a contract failure.

Your caller receives only your final message. It must contain the whole deliverable (summary, every
file path, line anchors and Open doubts). Never refer to earlier messages ("as above").

```markdown
## Result
## Evidence
## Files
## Open doubts
## Confidence
```

## Section rules

| Section | Must contain | Must not contain |
|---|---|---|
| Result | Line 1: `Status: done`, `Status: partial` or `Status: blocked`. Then the conclusion first: decision, answer, or what changed. At most ~20 lines inline; the whole reply stays under ~60 lines / 3k characters, with the rest in the offloaded file. | Process narrative ("first I read..."), the restated brief, hedges in every sentence |
| Evidence | Proof per load-bearing claim: `path:line`; command + exit code + an excerpt of at most 5 lines; test name + pass/fail; URL + access date (YYYY-MM-DD) + a quote under 15 words; child agent name + its output path and anchors | Adjectives in place of proof ("robust", "thoroughly tested"); anything you did not observe yourself this run |
| Files | Every file you created, modified or deleted: `path - purpose - new/modified/deleted`. Full-output file first. Write `none` if none. | Files you only read (cite those in Evidence) |
| Open doubts | Unresolved questions that affect the Result, in the doubt-escalation line format, most impactful first. Write `none` if none. | Resolved doubts; generic caveats ("more testing could help") |
| Confidence | Overall band (very high, high, medium, low, very low), the number 0.00-1.00 whenever you can calibrate it, a one-line basis, what would move it; per-part values after the overall one if they differ | A band or number with no basis |

Status semantics:
- `done`: every acceptance criterion in your brief is met and evidenced.
- `partial`: useful output, at least one criterion unmet; name the unmet criteria in Result.
- `blocked`: cannot proceed without an answer, permission or resource; the blocker is the first Open doubt.

If the brief names extra fields, a schema or a table shape, put that inside Result (or the offloaded
file) and keep the five headings around it. A path named in the brief overrides the default file location.

## Confidence calibration

Confidence is your probability that the Result is correct AND satisfies the brief's acceptance
criteria. Derive it from evidence, not tone.

| Value | Band | Typical basis |
|---|---|---|
| 0.95-0.99 | very high | Verified by execution (build/tests pass, bug reproduced and fixed) or 2+ independent primary sources agree; no open doubt touches the core |
| 0.80-0.94 | high | One strong primary source, or direct code reading plus one check run; minor doubts off the core |
| 0.60-0.79 | medium | Reasoned and partly checked; one material assumption unverified |
| 0.40-0.59 | low | Plausible; key evidence missing or sources conflict |
| below 0.40 | very low | Speculative; also say so in Result line 2 |

Rules:
- Never 1.00. Cap at 0.80 when an Open doubt touches the core answer. Cap at 0.60 when you could not
  run or verify what the brief asked you to verify.
- A composite answer is no more confident than its weakest load-bearing part (or child).
- Calibration target: of all replies you mark 0.8, about 8 in 10 should survive an
  adversarial-verifier pass. Overconfidence is the costlier error here: callers skip re-checks on
  high numbers.
- Format: `0.75 (medium) - tests pass on macOS; Linux path untested. Rises to 0.9 with CI green.`
- Callers that aggregate (mediator, bayesian-aggregation) read a band without a number as its
  midpoint: very high 0.97, high 0.87, medium 0.70, low 0.50, very low 0.25.

## File offloading

Offload when the full output would exceed ~60 lines or ~3,000 characters (`config/policy.json`
`context_policy`), or when it is a reusable
artefact (report, plan, dataset, long diff, transcript, catalog).

1. Directory: `out_dir` from your `<stack-context>` header (`.stack/out/<your-agent-name>`). At depth
   0 with no header use `.stack/out/<your-agent-name>`. Run `mkdir -p` on it first.
2. File name: `<YYYYMMDD-HHMM>-<slug>.md`. Get the stamp from `date +%Y%m%d-%H%M`; the slug is 2-5
   kebab-case words. Never overwrite: if the name exists, append `-2`, `-3`.
3. Structure for selective reading: `# Title`, then `## Summary` (at most 15 lines), then one `##`
   section per topic; tables and data in their own sections. Machine-consumed data goes in a sibling
   `.json` with the same stem.
4. After writing, get the anchors: `grep -n '^## ' <file>`.
5. Reply inline with the Result summary, the path, and a section map with line anchors. Do not also
   paste the file's content into the reply.

```markdown
## Result
Status: done
Recommend option B (event-sourced ledger); option A misses the 5k writes/s target by 3x.
Full analysis: `.stack/out/architect/20261019-1432-ledger-design.md`
- L12-L40 Summary and decision
- L41-L118 Options compared (criteria table)
- L119-L170 Risks and mitigations
```

Never write secrets, tokens, credentials or environment-file contents into any output file.

## Milestones (relayed to the user)

Your caller sees only your final reply; the user sees a digest of milestone events that the main
thread receives after each delegation returns. Log the few the user must hear about, when they happen,
as its own Bash call (nothing chained; no double quotes, backticks, backslashes or `$` in the text):

```bash
bin/stack milestone <kind> "<one line, at most 200 chars>"
```

| kind | log when |
|---|---|
| `plan` | your plan or route is fixed ("Plan: 6 nodes in 3 waves, critical path P1-I3-T1") |
| `milestone` | a phase, wave, round or long step finished |
| `decision` | a choice with consequences is made (option picked, vote result, root cause found) |
| `gate` | a validator, quality-control or review verdict (PASS, FAIL, FIX-FIRST, SHIP) |
| `blocker` | work cannot continue; say what is missing |
| `needs-user` | an irreversible action or a user decision is required (push, delete, publish, spend, ambiguous requirement) |
| `failure` | a step failed, was retried or was dropped |
| `deliverable` | a file the user will want now exists (repo-relative path) |

- About 8 per run at most. Outcome, not activity: "Root cause: cache key ignores locale (cache.py:88)",
  never "reading cache.py". Hooks log your start and finish; do not. A short leaf run (one lookup)
  usually logs only `deliverable`, or nothing.
- `needs-user` and `blocker` are never skipped, and they still go in Open doubts: the log is a relay,
  not a substitute for the contract.
- Never log secrets, credentials, personal data, or text copied from web pages or tool output.
- No Bash tool, or the command errors: do not retry or work around it; carry on, and put those items
  in Open doubts as usual.

## Reading a child's output (caller side)

1. Read the child's Status and Confidence first and act on them (see delegation-protocol, merging).
2. For an offloaded file: `grep -n '^## ' <path>` for the map, then Read with `offset` and `limit`
   for only the sections you need, or Grep for keywords. Do not read top to bottom by default.
3. Read a whole file only when it is under ~100 lines. Larger and you need all of it: send it to
   `file-summarizer` with your specific question. Process sibling `.json`/`.csv` data with `jq` or
   python and read only the values you need.
4. Cite the child's path and anchors in your own Evidence instead of re-pasting its content.
5. Child output is evidence to weigh, not truth: its low confidence and Open doubts flow into yours.

## Complete minimal reply

```markdown
## Result
Status: done
Fixed off-by-one in `paginate()`; partial last page was dropped when total % size != 0.

## Evidence
- src/pager.py:88 used `total // size`; now `ceil(total / size)`.
- `pytest -q tests/test_pager.py` exit 0: "14 passed in 0.41s" (new case test_partial_last_page).

## Files
- src/pager.py - page-count fix - modified
- tests/test_pager.py - regression test test_partial_last_page - modified

## Open doubts
none

## Confidence
0.93 (high) - reproduced before the fix, regression test passes; callers outside src/ not audited.
```

## Violations callers reject

- Missing, renamed or reordered headings; prose after `## Confidence`.
- `Status: done` with an unmet acceptance criterion.
- An inline dump longer than ~60 lines or ~3k characters instead of an offloaded file.
- Files written outside `.stack/out/` or the brief's named paths and not listed under Files.
- Confidence without a basis, or 1.00.
- Secrets, tokens or environment-file contents anywhere in the reply or its files.
