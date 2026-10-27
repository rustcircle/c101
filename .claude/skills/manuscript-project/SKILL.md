---
name: manuscript-project
description: "Specification of a fiction manuscript project on disk (manuscript.md front matter, chapters/NNN_slug.md, outline, bible, style sheet, reviews) and the manuscript.py CLI that scaffolds, validates, indexes, measures, inserts, renumbers and concatenates chapters, plus the shared report format and the fix-on-request protocol for writing agents. Load when creating, adopting, validating or restructuring a novel or story project, or before reading or writing chapter files."
when_to_use: "Starting a new novel folder, adopting an existing folder of chapters, adding or inserting or reordering chapters, regenerating the chapter list, finding where outline/bible/style sheet/reviews live, writing a review report, or editing chapter files on request."
---

# Manuscript project

One folder per book. Every writing agent reads and writes the same layout, so reports, chapter
anchors and the `/manuscript-review` workflow work on any project. Full key reference and custom
layouts: [layout spec](references/layout-spec.md).

## 1. Default layout

```
<project>/
  manuscript.md        front matter + logline, synopsis, generated chapter list
  chapters/NNN_slug.md 000_prologue.md, 001_chapter-1.md, 002_the-letter.md ...
  outline.md           "## NNN <title>" per chapter with beats
  bible/               characters.md, places.md, timeline.md, glossary.md
  style-sheet.md       spelling variant, house rules, names, voice notes, banned phrases
  reviews/             YYYYMMDD-HHMM-<kind>[-NNN].md reports
  notes/               free notes (optional)
```

| Path | Owner (who may write) | Readers |
|---|---|---|
| `manuscript.md` front matter | writing-project-builder | everyone |
| chapter list block in `manuscript.md` | `manuscript.py index --write` only | everyone |
| `chapters/*.md` | fiction-writer (files named in its brief); analysis agents only on an explicit fix request | everyone |
| `outline.md` | the user, fiction-writer when the brief says so | writer, reviewer |
| `bible/*.md` | fiction-writer (new facts it invents, listed in its reply), the user | writer, reviewer, copy-editor |
| `style-sheet.md` | copy-editor (new entries it decides), the user | copy-editor, writer, stylist |
| `reviews/` | copy-editor, prose-stylist, manuscript-reviewer | user, reviewer |

## 2. Names and front matter

- Chapter file name: `^(\d{3})_([a-z0-9][a-z0-9-]*)\.md$` by default. Three digits, underscore,
  lowercase kebab slug. `000` is free for a prologue; numbering normally starts at `001`.
- First non-front-matter line of a chapter is `# <Title>`. Everything after it is prose.
- Front matter is a tiny YAML subset: `key: value`, `key: [a, b]`, quoted strings, integers. No
  nesting, no block scalars, no PyYAML.

`manuscript.md` keys:

| Key | Default | Meaning |
|---|---|---|
| `title` | required | book title |
| `author` | empty | author name |
| `language` | `en-US` | selects word lists and copyediting rules |
| `pov` | empty | e.g. `first`, `close-third`, `omniscient`, `multiple-close-third` |
| `tense` | empty | `past` or `present` |
| `genre` | empty | free text, e.g. `literary`, `thriller`, `fantasy` |
| `target_words` | empty | integer word target for the whole book |
| `chapter_dir` | `chapters` | folder holding chapter files, relative to the project |
| `chapter_pattern` | see above | regex with exactly 2 groups: number, slug |

Chapter front matter (all optional): `pov` (viewpoint character), `timeline` (in-story date or
label), `status` (`outline`, `draft`, `revised`, `final`), `summary` (one line).

```markdown
---
pov: Mara
timeline: 1994-03-02
status: draft
summary: Mara finds the letter and lies to her brother about it.
---
# The Letter

The envelope had been opened once already...
```

The chapter list in `manuscript.md` lives between `<!-- chapters:start -->` and
`<!-- chapters:end -->`. Nothing else in the file is ever rewritten by tools.

## 3. Running manuscript.py

The script lives in the stack, not in the book folder. Resolve the stack root in the same Bash call
that uses it (shell variables do not persist between calls):

```bash
S="${CLAUDE_PROJECT_DIR:-}"; [ -d "$S/.claude/skills/manuscript-project" ] || S="$HOME/.claude/stack"
uv run --python 3.13 python "$S/.claude/skills/manuscript-project/scripts/manuscript.py" validate ~/books/salt-road
```

`$CLAUDE_PROJECT_DIR` is the stack repo when you run inside it; from a user-scope install the
scripts sit under `~/.claude/stack`. The script file is
`.claude/skills/manuscript-project/scripts/manuscript.py` (stdlib only, JSON on stdout, exit 0 ok,
1 check failed, 2 usage error, `--help` on every subcommand). Below, `M` stands for
`uv run --python 3.13 python "$S/.claude/skills/manuscript-project/scripts/manuscript.py"`.

| Subcommand | Use | Writes files |
|---|---|---|
| `M init <dir> --title T [--author A] [--language en-US] [--chapters 3] [--pov P] [--tense T] [--genre G] [--target-words N] [--start 0\|1]` | scaffold the default layout | yes, never overwrites (existing files reported under `skipped`) |
| `M validate <dir>` | check the layout; errors exit 1 | no |
| `M index <dir> [--write]` | chapter list with number, slug, file, title, words, status, pov and totals | only the chapter-list block with `--write` |
| `M stats <dir> [--chapter NNN]` | words, reading_minutes (250 wpm), dialogue_ratio, sentences, avg_sentence_words, paragraphs | no |
| `M new <dir> --slug S [--title T] [--after NNN]` | add a chapter; `--after` shifts later chapters up by one | yes (renames when `--after`) |
| `M renumber <dir> [--apply] [--start 0\|1]` | make numbering contiguous in current order; dry run by default | only with `--apply` |
| `M concat <dir> --out FILE` | whole manuscript in order, front matter stripped, H1s kept | the `--out` file (refused inside chapter_dir) |

`validate` findings:

| Finding | Level | Fix |
|---|---|---|
| no `manuscript.md`, unparsable front matter, `chapter_dir` missing | error | write or repair `manuscript.md` |
| file in chapter_dir not matching the pattern | error (warning if not `.md`) | rename (`renumber --apply` or by hand on request) or move to `notes/` |
| duplicate chapter numbers | error | `renumber` dry run, then `--apply` on request |
| chapter without an H1 | warning | add `# Title` as first prose line |
| `reviews/` or non-chapter files inside chapter_dir | warning | move them out |
| numbering gaps | warning | fine during drafting; `renumber` before final |

## 4. Procedures

**New project.** `M init <dir> --title "Salt Road" --author "A. Writer" --chapters 3 --pov close-third --tense past --genre literary`,
then `M validate <dir>` (expect exit 0), then `M index <dir> --write`. Fill `style-sheet.md`
spelling variant (`US, Merriam-Webster, CMOS 17/18`) and leave story content to the user or
fiction-writer.

**Custom structure** (user wants `parts/part-1/ch01-arrival.md` or `scenes/`): write
`chapter_dir` and a two-group `chapter_pattern` into `manuscript.md` front matter first, then
validate. Examples in [layout spec](references/layout-spec.md).

**Adopt an existing folder.** Never rename first. Run `M validate`, report what does not match,
propose either a `chapter_pattern` that matches the user's names or a `M renumber <dir>` dry-run
mapping. Rename (`--apply`) only when the brief asks for it.

**Add, insert, reorder.**

| Goal | Command |
|---|---|
| append chapter | `M new <dir> --slug the-crossing --title "The Crossing"` |
| insert after 004 | `M new <dir> --slug interlude --after 004` (005+ shift up, highest first) |
| move chapter 009 to sit after 003 | 1. `M new <dir> --slug slot --after 003` opens an empty `004_slot.md` (old 004-009 become 005-010, so the chapter is now `010_x.md`); 2. `mv chapters/010_x.md chapters/004_x.md` and delete the empty `004_slot.md` placeholder you just created; 3. `M renumber <dir>` dry run (closes the gap at 010), review, `--apply` |
| close gaps after deletions | `M renumber <dir>` then `--apply` |

Moves and renames change every `file:line` anchor in older reports; say so in the reply.

After any structural change: `M validate <dir>`, `M index <dir> --write`, and update `outline.md`
headings (`## NNN <title>`) to the new numbers.

## 5. Report files

Name: `reviews/<YYYYMMDD-HHMM>-<kind>[-NNN].md`, stamp from `date +%Y%m%d-%H%M`, kind one of
`copyedit`, `style`, `developmental`, `manuscript-review`; `-NNN` when the report covers a single
chapter. Never overwrite: append `-2`, `-3` on collision.

Every analysis report uses this shape (template and a filled example in
[layout spec](references/layout-spec.md)):

1. Header: project, chapters covered, date, reviewer agent, tool versions (`python3 --version`,
   script names, hunspell or LanguageTool version if used).
2. Summary table: `| category | count | high | med | low |`.
3. Findings: `| # | file:line | category | excerpt (<= 20 words) | why | suggestion |`, sorted by
   severity then position. `file:line` is the chapter path relative to the project and the line
   in the original file.
4. Strengths: 2-5 concrete bullets with anchors (what works and why).
5. Next steps: ordered, smallest number of actions that fix the most.

Severity: high = reader-visible error or a break in story logic; med = a pattern that weakens the
prose across a page; low = taste, optional polish.

## 6. Fix-on-request protocol (all analysis agents)

Report first. Edit a chapter file only when the brief explicitly asks for fixes, and then:

```bash
STAMP=$(date +%Y%m%d-%H%M); B=".stack/out/<agent>/$STAMP-backup"; mkdir -p "$B"
cp <project>/chapters/003_the-letter.md "$B/"           # before the first edit to each file
# ... apply edits with Edit (exact replacements, one finding at a time) ...
diff -u "$B/003_the-letter.md" <project>/chapters/003_the-letter.md > ".stack/out/<agent>/$STAMP-fixes.diff"
```

- Edit only lines named in findings; never reflow paragraphs or touch untouched lines.
- Put the unified diff in the reply when it is under ~60 lines, otherwise its path plus the hunk
  count; the backup directory always goes under Files.
- Never edit `bible/`, `outline.md` or `manuscript.md` front matter as part of a prose fix.

## 7. Privacy

Manuscript text is private. It never goes to web search, fetch, scraping or any MCP server. Local
tools only (the two stack scripts, hunspell or aspell if installed, LanguageTool only through a
server on `localhost`). Researchers may receive a factual question ("what did a 1994 London bus
ticket cost?") but never pasted manuscript text.

## 8. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `validate` errors on every file | user names like `Chapter 1.md` | pattern in front matter or renumber on request |
| chapter list stale | edits without `index --write` | run it after every structural change |
| report anchors off by a few lines | anchors taken from a concat file or a stripped view | anchor to the chapter file; scripts report original line numbers |
| two agents edit the same chapter | parallel fix requests | one writer per file per batch |
