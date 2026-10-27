---
name: copyediting
description: "US English fiction copyediting procedure (Merriam-Webster spelling, Chicago Manual of Style fiction defaults): spelling and typos, homophones and commonly confused words, dialogue punctuation, commas, dashes, ellipses, quotes, numbers, capitalization, hyphenation, grammar and tense or POV slips, consistency against the style sheet and story bible, style-sheet maintenance, and use of prose_check.py mechanics and consistency with optional local hunspell or LanguageTool. Load when copyediting or proofreading chapters."
when_to_use: "Copyedit or proofread a chapter or a whole manuscript, fix dialogue punctuation, check name and term spellings across chapters, normalize numbers, dashes or ellipses, build or update a style sheet, or check British spellings in a US English book."
---

# Copyediting (US English fiction)

Goal: correct, consistent, invisible mechanics while leaving the author's voice alone. Defaults are
Merriam-Webster (11th Collegiate, online) and CMOS 17/18 for fiction; the project's
`style-sheet.md` overrides them. Detailed rule tables: [US style rules](references/us-style-rules.md);
word pairs: [confused words](references/confused-words.md).

## 1. Procedure

1. Read `manuscript.md` front matter (`language` must be `en-US`; other variants: report the gap,
   do not apply US rules), `style-sheet.md` and `bible/glossary.md`, `bible/characters.md`.
2. Generate candidates with the stack script (resolve `$S` as in manuscript-project section 3):

   ```bash
   S="${CLAUDE_PROJECT_DIR:-}"; [ -d "$S/.claude/skills/manuscript-project" ] || S="$HOME/.claude/stack"
   P="$S/.claude/skills/prose-style-analysis/scripts/prose_check.py"
   uv run --python 3.13 python "$P" mechanics <project>/chapters/003_the-letter.md --top 200 --out .stack/out/copy-editor/003-mechanics.json
   uv run --python 3.13 python "$P" consistency <project> --out .stack/out/copy-editor/consistency.json
   ```

3. Optional local spellers (never a web API): `command -v hunspell && hunspell -d en_US -l <file>`
   lists unknown words; LanguageTool only if a server answers on localhost
   (`curl -s --max-time 2 http://localhost:8081/v2/languages`), then
   `curl -s --data-urlencode "text@<file>" -d language=en-US http://localhost:8081/v2/check`.
   No local server: skip it and say so in the report header.
4. Read every flagged line in context (Read with offset/limit around the line). Script flags are
   candidates; about a third are false positives in fiction (dialect, voice, deliberate fragments).
5. Read the chapter straight through once more for what scripts cannot see: agreement, dangling
   modifiers, tense slips, wrong word that is a real word, missing words, continuity of small facts.
6. Classify each confirmed issue (category, severity), write the finding with `file:line`, the
   excerpt (20 words max), why (the rule, briefly) and the exact replacement.
7. Collect style decisions you made (a spelling, a hyphenation, a capitalization) as proposed
   style-sheet entries.
8. Write the report (manuscript-project section 5 format) to `reviews/<stamp>-copyedit-NNN.md`.

## 2. Categories and severity

| Category | Includes | Default severity |
|---|---|---|
| spelling | typos, British forms in a US book, wrong compound form | high |
| confused-word | its/it's, affect/effect, lose/loose, then/than | high |
| punctuation | dialogue punctuation, commas that change meaning, quote marks, dashes, ellipses | high if it misleads, else med |
| grammar | agreement, case (between you and I), dangling modifiers, run-ons, unintended fragments | med (high if meaning breaks) |
| tense-pov | tense slip against front matter, POV knowledge slip | high |
| consistency | names, invented terms, capitalization, hyphenation, numbers vs style sheet | med (high for names) |
| typography | double spaces, straight/curly mix, `--` for dashes | low |

## 3. Dialogue punctuation (the most frequent findings)

| Case | Correct | Wrong |
|---|---|---|
| statement + tag | "I know," he said. | "I know." he said. |
| question + tag | "Do you?" she asked. | "Do you?," she asked. / "Do you?" She asked. |
| exclamation + tag | "Run!" he yelled. | "Run!," he yelled. |
| tag first | He said, "I know." | He said "I know." |
| action beat, not a tag | "I know." He set the cup down. | "I know," he set the cup down. |
| interrupted tag | "I know," he said, "but not yet." | "I know," he said. "but not yet." |
| tag between two sentences | "I know," he said. "Not yet." | "I know," he said, "Not yet." |
| interruption | "I was going to—" "Don't." | "I was going to-" |
| trailing off | "I thought…" | "I thought..." when the sheet says `…` |
| quote inside dialogue | "She said 'never,' so." | "She said "never," so." |
| multi-paragraph speech | open quote at each paragraph, close only at the end | closing quote on every paragraph |
| direct address | "Come here, Mara." | "Come here Mara." |
| verbs that are not speech | "Fine." She smiled. | "Fine," she smiled. |

Tag capitalization: lowercase after a comma, question or exclamation mark ("Do you?" she asked).
Punctuation goes inside the closing quotes (US).

## 4. Core rules (summary)

- **Serial comma**: always ("bread, salt, and rope").
- **Commas**: after introductory clauses of more than four or five words or when needed for clarity;
  before a coordinating conjunction joining two independent clauses (optional when both are short);
  around nonrestrictive clauses ("My brother, who lives in Leeds, called" means one brother).
  Comma splices are errors unless deliberate voice in short paired clauses ("He wasn't coming, he
  never came.") - flag as low with a note.
- **Em dash**: closed, no spaces (word—word); for interruption in dialogue end with `—` inside the
  quote. **En dash**: number ranges (1994–1996). Hyphen: compounds only. `--` or ` - ` used as a
  dash is a typography finding.
- **Ellipsis**: one style per book (three periods or `…`); CMOS spaces between periods (`. . .`) are
  acceptable if the style sheet says so; trailing-off speech ends with the ellipsis inside the quote.
- **Numbers**: spell out zero to one hundred, round numbers (two thousand, three million), numbers
  starting a sentence; digits for years, times with a.m./p.m. ("4:15 a.m."), addresses, decimals.
  In dialogue, spell out nearly everything ("nineteen ninety-four" is fine in speech).
- **Capitalization**: titles before names ("Captain Vell") but not alone ("the captain"); family
  words as names ("Mom said" vs "my mom said"); seasons lowercase; invented proper nouns per
  glossary.
- **Hyphenation**: compound modifiers before a noun ("a well-known man"), not after ("he was well
  known"); no hyphen after -ly adverbs ("a badly built boat"); check MW for closed compounds
  (lifeboat, makeup, toward).
- **Italics**: internal thoughts per style sheet (CMOS allows roman), foreign words not in MW,
  titles of books, ships, emphasis sparingly.

Full tables (more number cases, hyphenation list, capitalization of titles, possessives of names
ending in s): [US style rules](references/us-style-rules.md).

## 5. British to US spelling

Common pairs (the script's `british_to_us` word list has 150+): colour/color, realise/realize,
travelling/traveling, grey/gray, towards/toward, amongst/among, whilst/while, learnt/learned,
practise (verb)/practice, defence/defense, centre/center, kerb/curb, tyre/tire, programme/program,
mum/mom (only in narration of US characters; in dialogue it is character voice).

False positives: proper nouns ("Centre Street" in London), quoted British characters' speech,
deliberate setting voice. Check the style sheet before flagging.

## 6. Grammar and slips worth a careful read

- Subject-verb agreement across intervening phrases ("The box of letters was").
- Pronoun reference: two same-gender characters in a scene, "she" ambiguous.
- Dangling modifiers: "Walking to the dock, the boat came into view." (the boat was not walking).
- Lie/lay, who/whom (in narration; leave dialogue to voice), fewer/less.
- Tense: past-tense book slipping into present outside dialogue and deliberate present thoughts;
  past perfect needed when entering a flashback.
- POV knowledge: close-third narrator naming something the viewpoint character cannot know.
- Fragments: fine as voice ("Never again."), wrong when a subordinate clause is cut off ("Because
  the tide was turning." standing alone without intent).

## 7. Consistency audit

1. Run `consistency` on the project; it returns name/term variants (edit distance 2 or less),
   hyphenation variants and capitalization variants with chapter anchors.
2. For each cluster, decide the canonical form: glossary or bible first, then style sheet, then the
   majority form, then MW. Never "fix" the canonical spelling itself.
3. Report each variant occurrence as a consistency finding; propose the sheet entry.
4. Small-fact continuity you notice (eye color, ages, day of week) is a consistency finding cited
   against the bible line; plot-level continuity goes to manuscript-reviewer.

## 8. Style-sheet maintenance

Propose entries in the report under "Next steps" as a block the user can paste:

```markdown
| term | form | notes |
|---|---|---|
| the Saltings | capitalized | place name; "saltings" lowercase only as a common noun |
| ice cream | open as noun, hyphenated as modifier (ice-cream cone) | MW |
```

Write to `style-sheet.md` yourself only if the brief allows it; otherwise propose.

## 9. Fixing on request

Default is report-only. When the brief explicitly asks for fixes, follow the manuscript-project fix
protocol: back up each chapter to `.stack/out/copy-editor/<stamp>-backup/` before the first edit,
apply only the reported findings with exact Edit replacements, never touch dialogue voice (dialect,
"gonna", fragments) unless a finding says why, and return `diff -u` output of every change.

## 10. Worked example

Script flag: `003_the-letter.md:41 dialogue_punct "I know." he said.` Read lines 38-44: it is a
tag, not a beat. Finding: `| 1 | chapters/003_the-letter.md:41 | punctuation | "I know." he said. |
period before a lowercase tag; US uses a comma | "I know," he said. |` Severity med.

Script flag: `003:57 confused_word its` in "its been years". Confirmed, high: `it's been years`.

Script flag: `003:62 number_style 12` in "the 12 boats". Narrative, under 101: med, "the twelve
boats". Same flag at 003:90 in "the 12:40 ferry": time, false positive, drop it.

## 11. Pitfalls

| Pitfall | Avoid by |
|---|---|
| correcting dialect or voice in dialogue | treat dialogue as the character's; flag only mechanics |
| applying CMOS where the style sheet differs | read the sheet first; it wins |
| reporting every script flag | read each in context; drop false positives |
| rewriting sentences | copyedit changes mechanics, not style; style goes to prose-stylist |
| anchors to concatenated text | always anchor to the chapter file line |
