---
name: developmental-editing
description: "Developmental (structural) editing of fiction: a structural review checklist, beat and structure models (three-act, Save the Cat, try-fail cycles, scene-sequel) used as lenses not rules, plot-logic and stakes audit, POV and tense discipline, character arc and motivation audit, continuity audit against the story bible and timeline, a pacing map from manuscript.py stats, chapter openings and endings, global-before-local prioritization and the developmental and merged manuscript-review report templates. Load when reviewing the structure of a draft or synthesizing a whole-book review."
when_to_use: "Whole-book or multi-chapter review, 'does the middle sag', 'is the ending earned', plot holes and continuity errors against the bible, character motivation problems, pacing map, or merging copyedit and style reports into one prioritized manuscript review."
---

# Developmental editing

Developmental editing answers "does the story work?" before anyone asks "is the sentence right?".
Findings are about scenes, chapters and arcs, anchored to `file:line` ranges, and prioritized
global before local. Models and templates in depth:
[structure models](references/structure-models.md), [review formats](references/review-formats.md).

## 1. Inputs to gather

| Input | How | Why |
|---|---|---|
| chapter list, words, status, pov | `manuscript.py index <project>` | scope and proportions |
| stats per chapter | `manuscript.py stats <project>` | pacing map (words, dialogue ratio, sentence length) |
| outline | `outline.md` | intent vs what is on the page |
| bible | `bible/characters.md`, `timeline.md`, `places.md`, `glossary.md` | continuity reference |
| front matter | `manuscript.md` (pov, tense, genre, target_words) | contract the book declared |
| prior reviews | `reviews/*.md` (latest of each kind) | do not repeat; check what was fixed |

Run the script as in manuscript-project section 3. For more than ~40k words, do not read every
chapter in full yourself: get per-chapter digests (summary, POV, timeline markers, goal, outcome,
new facts, open questions, last paragraph) from fresh-context summarizers and read in full only the
chapters where a structural finding lands.

## 2. Structural review checklist

**Premise and contract**
- [ ] The central dramatic question is clear by the end of the first act (about 20-25%).
- [ ] The opening chapters promise the book that follows (genre, tone, kind of conflict).
- [ ] The ending answers the central question in action, not in summary.

**Plot logic and stakes**
- [ ] Every major event is caused by a prior event or choice (because, not and-then).
- [ ] Coincidence helps the protagonist at most once and never at the climax.
- [ ] Stakes are personal and escalate; the cost of failure is clear by the midpoint.
- [ ] Antagonistic force is active and competent; it acts off-page and the effects show on-page.
- [ ] No plot holes: information a character uses was available to them; no capability appears
      only when needed.

**Scenes and sequence**
- [ ] Each scene has a goal, conflict and changed outcome (fiction-craft section 2); list scenes that
      do not turn.
- [ ] Sequels exist after big scenes; no chain of scenes without reaction, no chain of reflection
      without action.
- [ ] Scene order: cause before effect; flashbacks placed where the question they answer is hot.

**POV and tense discipline**
- [ ] POV per chapter matches front matter or chapter `pov:`; no head-hopping inside scenes.
- [ ] Each POV character earns their chapters (has a goal and an arc), voices are distinct.
- [ ] Tense consistent; deliberate shifts signalled.

**Characters**
- [ ] Protagonist wants something concrete (goal) and needs something deeper (arc); both resolve.
- [ ] Motivation: every major choice is legible from what the character knows and wants.
- [ ] Agency: the protagonist drives the climax; rescue by others is a high finding.
- [ ] Secondary characters change or reveal; no character exists only to deliver information.

**Continuity**
- [ ] Facts match the bible: names, ages, appearance, relationships, places, rules of the world.
- [ ] Timeline holds: days of the week, travel times, seasons, ages across years, pregnancy and
      healing durations; `bible/timeline.md` order matches chapter order or flashbacks are marked.
- [ ] Objects and wounds persist (the cast on the arm, the burned letter does not reappear).

**Pacing and proportion**
- [ ] Act proportions near the lens (about 25 / 50 / 25) or deliberately different.
- [ ] No sag: the middle has a midpoint reversal and escalating try-fail cycles.
- [ ] Chapter lengths fit the genre; outliers (2x the median) have a reason.

**Openings and endings**
- [ ] Each chapter opening anchors POV, place, time within the first page.
- [ ] Each chapter ending turns, decides, raises a question or lands an image.

## 3. Structure models as lenses

Use a model to ask questions, never to demand a beat at a page number.

| Model | Ask | Signals of trouble |
|---|---|---|
| three-act | where are the inciting incident (~10-15%), first plot point (~25%), midpoint (~50%), crisis and climax (~75-95%)? | nothing changes at the midpoint; climax before 85% with a long tail |
| Save the Cat (15 beats) | is there a catalyst, a debate, a break into two, fun and games, bad guys close in, all is lost, dark night, finale? | "all is lost" missing, so the ending is not earned |
| try-fail cycles | does the protagonist try, fail (yes-but, no-and) and escalate at least twice before succeeding? | success on the first try; failures that do not change tactics |
| scene-sequel chain | do action units alternate with reaction units? | relentless action (numbness) or relentless reflection (stall) |
| MICE quotient | which thread (milieu, inquiry, character, event) opens first, and do threads close in reverse order? | the book opens an inquiry and ends on an event thread |

Beat tables and percentages: [structure models](references/structure-models.md).

## 4. Pacing map from stats

```bash
S="${CLAUDE_PROJECT_DIR:-}"; [ -d "$S/.claude/skills/manuscript-project" ] || S="$HOME/.claude/stack"
uv run --python 3.13 python "$S/.claude/skills/manuscript-project/scripts/manuscript.py" stats <project> > .stack/out/manuscript-reviewer/stats.json
jq -r '.chapters[] | [.number, .words, .dialogue_ratio, .avg_sentence_words] | @tsv' .stack/out/manuscript-reviewer/stats.json
```

(Adjust the jq path to the actual JSON keys; inspect with `jq 'keys'` first.) Build a table per
chapter: number, words, cumulative % of book, dialogue ratio, average sentence length, your one-line
"turn" for the chapter, and a tension mark (rising, flat, falling). Read it for:

| Pattern | Possible meaning |
|---|---|
| several consecutive chapters with low dialogue ratio and long sentences | reflective stretch; check that something turns |
| a chapter 2x the median length | two chapters or a bloated sequel |
| midpoint (50% cumulative) chapter has no turn | sagging middle |
| dialogue ratio jumps near the climax and words per chapter drop | normal acceleration |
| last 10% holds more than three chapters of wrap-up | long tail after the climax |

## 5. Continuity audit procedure

1. Extract facts per chapter (names, ages, physical traits, dates, places, objects, injuries, rules)
   via digests, then diff them against `bible/` entries.
2. Rebuild a timeline from chapter `timeline:` front matter and in-text markers; check day counts,
   travel times, seasons, ages.
3. Each contradiction is a finding with both anchors: `chapters/004_x.md:88 vs bible/characters.md:12`.
4. Facts present in chapters but missing from the bible go to "Next steps" as proposed bible entries
   (the reviewer proposes; fiction-writer or the user updates the bible).

## 6. Prioritization

1. **Global**: premise, central question, ending, protagonist arc and agency, act structure.
2. **Sequence**: missing or redundant scenes, order, POV allocation, pacing sag.
3. **Scene**: scenes that do not turn, weak openings and endings, motivation gaps.
4. **Continuity**: contradictions against bible and timeline.
5. **Line** (only when synthesizing): style families and copyedit categories, by density.

Severity for developmental findings: high = breaks the story contract or logic (reader stops
believing); med = weakens a sequence or an arc; low = local improvement. Recommend the smallest
change that fixes the most (moving one revelation often fixes three motivation findings).

## 7. Synthesis of a whole-book review

When copy-editor and prose-stylist reports exist (the `/manuscript-review` workflow passes their
summaries and report paths):

1. Read each per-chapter summary (counts by category and severity, top issues, path). Open a report
   only to check a top issue or a conflict, with Grep on the findings table.
2. Aggregate counts into one table by chapter x category; mark chapters 2x the median on any
   category.
3. Deduplicate: the same line flagged by both agents keeps the higher severity and both categories.
   Conflicts (copy-editor fixes a fragment the stylist calls voice) resolve toward the style sheet
   voice notes, otherwise list as a decision for the author.
4. Recurring patterns across chapters become book-level findings (one finding, many anchors), not
   N copies.
5. Run your developmental pass (sections 2-5) and put it first.
6. Write `reviews/<stamp>-manuscript-review.md` with the template in
   [review formats](references/review-formats.md): developmental findings, then
   book-level line patterns, then per-chapter tables with links to the chapter reports, then a
   revision plan in priority order.

## 8. Worked example (compressed)

Book: 82k words, 24 chapters, close third, two POVs. Stats: chapters 11-15 average 4,900 words
(median 3,300), dialogue ratio 0.12 (book 0.31). Outline puts the midpoint reversal in chapter 12;
on the page, chapter 12 is Mara remembering the flood, no event changes her situation. Continuity:
the surveyor arrives "on a Tuesday" (003:14) and the storm hits "two days later, Friday" (005:3).

Findings: high - the midpoint does not turn (012:1-210), recommend moving the burning of the letter
(now 016:44-90) into chapter 12; med - chapters 11-15 reflective sag, cut or merge 13 and 14
(combined 9,800 words); med - weekday contradiction 003:14 vs 005:3, propose Wednesday.

## 9. Pitfalls

| Pitfall | Instead |
|---|---|
| line-editing in a developmental report | park line notes; one sentence pointing to the style report |
| enforcing a beat sheet | ask what the beat would do and whether something else does it |
| vague notes ("the middle drags") | anchor the sag, quantify it, propose a concrete change |
| rewriting the author's book | diagnose and propose options; the author decides |
| reading 100k words into context | digests from summarizers, full reads only where findings land |
