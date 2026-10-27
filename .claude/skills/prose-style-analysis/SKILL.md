---
name: prose-style-analysis
description: "Line-level fiction style analysis: the three avoid-prose families (purple prose and overwriting, generic or AI-sounding prose, filter words and weak verbs) plus show-not-tell, dialogue tags, repetition and sentence rhythm, each with detection heuristics, false-positive guidance (deep POV, deliberate telling, voice-driven fragments), before/after rewrite patterns, simplification to a target Flesch-Kincaid grade that keeps the voice, and how to run prose_check.py style and readability and read its metrics. Load when analyzing or tightening prose style."
when_to_use: "Style pass on a chapter, 'this reads like AI', overwritten or flowery prose, too much telling, filter words, said-bookisms, monotonous sentence rhythm, repeated words or openers, simplify a chapter to grade 6, or self-checking a freshly drafted chapter."
---

# Prose style analysis

Find the patterns that weaken prose, prove each with an anchor, and suggest a rewrite in the
author's voice. Metrics locate candidates; judgment decides. Rewrite catalog:
[rewrite patterns](references/rewrite-patterns.md); generic-prose catalog:
[generic prose](references/generic-prose.md).

## 1. Running the checker

```bash
S="${CLAUDE_PROJECT_DIR:-}"; [ -d "$S/.claude/skills/manuscript-project" ] || S="$HOME/.claude/stack"
P="$S/.claude/skills/prose-style-analysis/scripts/prose_check.py"
uv run --python 3.13 python "$P" style <project>/chapters/003_the-letter.md --top 15 --out .stack/out/prose-stylist/003-style.json
uv run --python 3.13 python "$P" style <project> --checks filter_words,ai_tells,purple --top 10   # whole book via manuscript.md
uv run --python 3.13 python "$P" readability <project>/chapters/003_the-letter.md
```

Script: `.claude/skills/prose-style-analysis/scripts/prose_check.py`, word lists in its
`wordlists/en-US.json` (per language; other languages need their own file). It skips front matter,
headings, fenced code and HTML comments, keeps original line numbers, and treats text inside straight
or curly double quotes as dialogue. Stdout is a summary (counts per check per file, top flags);
`--out` gets the full JSON: `.files[]` with `counts`, `metrics` (densities per 1000 words), `words` and `flags`
`{file, line, col, check, match, context, severity}`. Process the JSON with `jq` or `python3 -c`;
never read it whole into context.

```bash
jq -r '.files[].flags[] | select(.severity=="high") | "\(.file):\(.line) \(.check) \(.match)"' .stack/out/prose-stylist/003-style.json | head -40
```

`style` checks: `filter_words`, `weak_verbs`, `adverbs`, `dialogue_tags`, `intensifiers`, `cliches`,
`ai_tells`, `tell_emotion`, `purple`, `repetition`, `rhythm`.

## 2. Reading the metrics

Absolute thresholds are rough; compare a chapter with the book median and with the author's best
chapter first. A chapter 2x the book median on a check is a stronger signal than any fixed number.

| Metric (per 1000 words) | Usually fine | Look closer | Likely problem |
|---|---|---|---|
| filter words (saw, felt, heard, noticed, realized, wondered, seemed) | < 5 | 5-10 | > 10 |
| -ly adverbs (narration) | < 8 | 8-15 | > 15 |
| intensifiers (very, really, so, just, quite, utterly) | < 4 | 4-8 | > 8 |
| was/were + -ing, began/started to | < 6 | 6-12 | > 12 |
| similes ("like a", "as ... as") | < 3 | 3-6 | > 6 |
| exclamation marks in narration | 0 | 1-2 | > 2 |
| tell_emotion hits | < 2 | 2-5 | > 5 |
| ai_tells + cliches | 0-1 | 2-4 | > 4 |

Rhythm: sentence-length stdev below ~5 words reads monotone; runs of 4+ similar-length sentences
are flagged; more than ~10% of sentences over 35 words is heavy for commercial fiction, normal for
some literary voices. Repetition: a non-stopword repeated within 50 words, or the same sentence
opener three times in a row (She ... She ... She ...).

## 3. Family 1: purple prose and overwriting

Detect: adjective stacks (two or more adjectives before a noun, repeatedly), piled similes and
metaphors (two figures for one thing), intensifiers, melodramatic verbs (shattered, screamed,
exploded used for small events), abstract grandeur (eternity, infinite, soul) in ordinary moments,
exclamation marks in narration, thesaurus words where plain ones fit.

| Before | After |
|---|---|
| The ancient, crumbling, moss-covered stone wall loomed ominously like a sleeping giant. | The wall was older than the town, furred green where the tide reached it. |
| Her heart shattered into a million tiny pieces. | She put the letter face down and kept her hand on it. |

False positives: a narrator whose voice is ornate by design (gothic, unreliable, comic); a deliberate
emotional peak; period pastiche. Check the style sheet's voice notes before flagging; flag density
and sameness, not ornament itself.

## 4. Family 2: generic and AI-sounding prose

Detect: stock phrases and cliches (word list), hedges ("a sense of", "somehow", "almost as if"),
tidy triplets (three adjectives or clauses in a row, every paragraph), abstract emotion summaries
("a wave of relief washed over her"), paragraph-ending moral or insight lines ("And in that moment,
she knew everything would change."), symmetrical "not X, but Y" constructions, filler transitions
("Little did she know"), sensory checklists (one sight, one sound, one smell per paragraph), and
words that machine text overuses (testament, tapestry, palpable, unspoken, intricate, delve,
whisper of, a dance of). Catalog with replacements: [generic prose](references/generic-prose.md).

| Before | After |
|---|---|
| A wave of relief washed over her, and she let out a breath she didn't know she was holding. | Her shoulders came down. She hadn't noticed they were up. |
| The air was thick with tension, a palpable reminder of everything left unsaid. | Nobody passed the salt. |
| It was a testament to their bond, a tapestry woven from years of shared silence. | (cut; the scene already showed it) |

Rewrite principle: replace the generic summary with the one concrete detail only this character in
this place would notice, or cut it when the scene already did the work.

False positives: a cliche in dialogue that characterizes the speaker; a stock phrase subverted on
purpose; genre idiom expected by readers (romance beats, hard-boiled similes) used sparingly.

## 5. Family 3: filter words and weak verbs

Filter words put a perceiving layer between reader and experience: "She saw the boat drift" becomes
"The boat drifted." Weak verbs: "was walking" (when simple past works), "began to run", "started to
cry", "there was a man who", "it was the cold that", nominalizations ("made a decision" for
"decided"), verb + adverb for a precise verb ("walked slowly" for "trudged" when that is accurate).

| Before | After |
|---|---|
| She felt the cold seep through her boots. | The cold seeped through her boots. |
| He noticed that the door was open. | The door was open. |
| There was a man standing by the sluice. | A man stood by the sluice. |
| She began to run. | She ran. |

False positives (keep the filter word):
- Deep POV where the act of perceiving matters ("She heard it before she saw it" - order of
  perception is the point).
- Uncertainty or misperception ("She thought she saw him" - the doubt is the content).
- Emphasis on the perceiver's limits in a suspense beat.
- Progressive aspect for interrupted or simultaneous action ("She was tying the knot when the
  shout came.") is correct grammar, not weak.

## 6. Show, don't tell

Detect: named emotions (felt/was/seemed + emotion word, "with anger"), explained subtext ("which
meant she was scared"), conclusions handed to the reader ("He was a cruel man."), summary where the
reader was promised a scene (a confrontation reported in two sentences).

Rewrite toward: action and gesture, dialogue and its subtext, physical sensation, choice under
pressure, concrete detail. One strong beat beats three.

| Before | After |
|---|---|
| Tomas was furious. | Tomas set the mug down hard enough to slop it. |
| She was scared of the dark marsh. | She kept the lamp between herself and the reeds. |

Telling is right (do not flag, or flag low with a note): transitions and time jumps, routine action,
deliberate retrospective or omniscient narration, a compressed sequel after a big scene, backstory
that a scene would bloat, and naming an emotion the character is surprised to discover ("She was,
she realized, happy."). See fiction-craft section 9.

## 7. Dialogue tags

- `said`/`asked` are invisible; keep them. Said-bookisms (hissed, growled, chortled, exclaimed,
  ejaculated, opined) are flagged; one per chapter is often fine, one per page is not. Some cannot
  carry speech ("hissed" a line with no s sounds; "smiled" a line - that is a punctuation error too).
- Adverb tags ("she said angrily") tell what the line should show; replace with a better line or a
  beat, or cut the adverb.
- Beats instead of tags: identify the speaker and pace the exchange; do not attach a beat to every
  line.
- Long exchanges between two people can run 4-6 lines untagged; re-anchor after that.

## 8. Repetition and rhythm

- Echoes: the same striking word twice within a short span (the script's 50-word window). Common
  words (said, the, was) do not count; distinctive ones do ("crimson ... crimson").
- Openers: three sentences in a row starting with the same word or structure (She ... She ...;
  -ing clause, -ing clause).
- Length: vary it. A short sentence after long ones lands; a run of medium sentences drones.
- Paragraph shape: same length and shape every time flattens pace; big moments get white space.

Rewrite by combining, inverting, or cutting, not by swapping in synonyms (elegant variation reads
worse than repetition: "the boat ... the vessel ... the craft").

## 9. Simplification to a target grade

On request only ("simplify chapter 3 to grade 6"). Method:

1. Measure: `readability` gives Flesch Reading Ease, Flesch-Kincaid grade, words per sentence,
   syllables per word, % long words and the 10 hardest paragraphs with line numbers.
2. Set the target from the brief or the genre: middle grade 4-7, YA 6-9, commercial adult 6-9,
   literary 8-12. A reasonable tolerance is target plus or minus 0.5.
3. Rewrite hot spots first: split sentences over ~25 words at conjunctions and relative clauses;
   replace Latinate or abstract words with concrete short ones where the character would use them;
   turn nominalizations into verbs; cut stacked qualifiers.
4. Keep the voice: dialogue diction stays the character's; keep signature images, rhythm contrasts
   (leave some long sentences) and the chapter's beats. Simplifying vocabulary is not removing
   content.
5. Re-measure and report before/after grade, reading ease and words per sentence per file.

FK grade = 0.39 x (words / sentences) + 11.8 x (syllables / words) - 15.59. Reading Ease = 206.835
- 1.015 x (words / sentences) - 84.6 x (syllables / words). Both are syllable heuristics; dialogue-
heavy text scores easier than it reads. Treat a 1-grade difference as noise.

## 10. Severity

| Severity | Meaning |
|---|---|
| high | a pattern a typical reader notices on the page (named emotion at a climax, three cliches in a paragraph, AI-tell paragraph endings throughout, a said-bookism every few lines) |
| med | density above the book median on one check, sentence monotony across a page, filter words in action scenes |
| low | single instance, taste, optional polish |

## 11. Procedure for a style report

1. Read the style sheet voice notes and front matter (pov, tense, genre).
2. Run `style` (and `readability` when rhythm or simplification is in scope) with `--out` JSON.
3. Rank checks by density against the book median; pick the top families for this chapter.
4. Read each high flag and a sample of med flags in context; drop false positives with the reason
   class (deep POV, deliberate telling, voice fragment, dialogue characterization).
5. Write findings with a concrete rewrite in the author's voice for each high finding and for one
   representative per med pattern; do not rewrite every instance of a pattern.
6. Strengths: name what works with anchors (a scene that shows well, a voice that is distinct).
7. Report to `reviews/<stamp>-style-NNN.md` (manuscript-project section 5 format).

## 12. Self-check for writers

After drafting, run `style --top 10` on the new chapter. Fix every high flag or keep it with a
reason; compare densities with the previous two chapters; read the chapter's last paragraph for a
moral-summary ending; check that no emotion named in narration is already shown in the same beat.
