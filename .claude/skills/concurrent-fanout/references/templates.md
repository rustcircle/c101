# Fan-out templates

Copy, fill the angle-bracket fields, keep the structure. Procedure and rules: [../SKILL.md](../SKILL.md).

## 1. Item brief (full)

````
GOAL: <operation, e.g. "extract every HTTP endpoint"> for ONE item.
ITEM: <id> = <path | URL | claim text | module name>
CONTEXT: This is item <k> of <N> in fan-out run <run-slug>. Other items are handled by other agents
  concurrently; do not read or modify anything outside your item except to resolve a reference
  (at most 3 such reads; list them in Evidence).
INPUTS: <paths with line ranges, URLs; shared reference docs by path>
TASK: <steps or questions for this item>
ACCEPTANCE: <checkable: "every route registration in <path> accounted for", "verdict with a quote and URL">
WRITE: full details to .stack/out/<agentType>/<run-slug>/<id>.md (mkdir -p first); its first line
  is your Status line. If that file already exists and its first line is "Status: done", return its
  result unchanged without redoing the work.
RETURN: output-contract. Result line 1: Status: done|partial|blocked. Then this block, exactly:
  ```json
  {"id": "<id>", "status": "<same as Status>", "summary": "<= 2 sentences",
   "data": {<flat fields: name: type>}, "file": "<the path above>", "confidence": <0..1>,
   "error": <null or one-line reason>}
  ```
BUDGET: about <k> tool calls. If you cannot finish, return Status: partial with what is missing.
DOUBTS: per doubt-escalation; scope doubts go back to me, do not guess.
````

## 2. JSON Schema for /fanout or validation

```json
{ "type": "object",
  "properties": {
    "id": {"type": "string"},
    "status": {"type": "string", "enum": ["done", "partial", "blocked"]},
    "summary": {"type": "string", "maxLength": 400},
    "file": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "error": {"type": ["string", "null"]},
    "<metric>": {"type": "integer"}
  },
  "required": ["id", "status", "summary"] }
```

With `/fanout`, put task fields at the top level of the schema (flat). With direct Agent calls, the
same fields go under `data` in the JSON block; `collate.py` accepts both.

## 3. Retry briefs

Never resend the original unchanged. Prepend one of these to the original brief.

**crash**
```
RETRY (attempt 2 of 2): the previous attempt returned no result. Keep scope minimal, write the file
early, and return the JSON block even if partial.
```

**contract**
```
RETRY (attempt 2 of 2): your previous reply lacked <fields> / had invalid <field> (<what was wrong>).
Your work file <path> exists; reuse it. Return Result with Status and the exact JSON block shape below.
```

**exhausted** (with the next-tier agent, or a narrower scope)
```
RETRY (attempt 2 of 2): the previous attempt ran out of turns after <what it covered>. Narrowed scope:
<subset>. Skip <expensive step>. Return partial rather than exceeding <k> tool calls.
```

**off-brief**
```
RETRY (attempt 2 of 2): the previous reply answered <what it did> instead of <what was asked>.
Required output: <restate>. Item: <id> only.
```

## 4. Normalize brief (cheap repair instead of a full retry)

Use agent `file-summarizer` (LOW tier; no model/effort on the call) when the item's work file exists
but its reply broke the contract.

```
GOAL: extract the item result for <id> from .stack/out/<agentType>/<run-slug>/<id>.md.
Return ONLY the JSON block with fields <list>; use null for anything the file does not state.
Do not add facts. Status partial if the file says work was incomplete.
```

## 5. Batch message layout (direct Agent calls)

One message, one Agent call per item:

| Field | Value |
|-------|-------|
| `subagent_type` | exact agent name, e.g. `fact-checker` |
| `description` | `<verb> <id>`, 3-6 words, e.g. `Fact-check claim c07` |
| `prompt` | the item brief |
| `run_in_background` | `false` (you collate these results this turn); never set `model`/`effort`, the pre-agent hook strips them |

Keep a ledger while batches run in a file, `.stack/out/<you>/<run-slug>-ledger.md` (never TodoWrite):

```
run 20261019-1600-endpoints  N=14  batch size 14  budget H/2=169
| id | attempts | status | class | note |
| i01-auth | 1 | done | | |
| i13-legacy-gw | 2 | done | exhausted -> security-auditor (ADVANCED), narrowed | |
```

## 6. Collation

```bash
# results.json: array of item JSON blocks (or the /fanout return object)
python3 .claude/skills/concurrent-fanout/scripts/collate.py results.json \
  --expect $(cat .stack/out/<you>/<run-slug>-ids.txt) \
  --metrics endpoints unauthenticated \
  --md .stack/out/<you>/<run-slug>-results.md
```

Output: the table, `Coverage: 13/14 done, 1 partial (i02-billing).`, and totals over done items.
`--expect` turns items with no result into explicit `failed` rows; always pass it.

## 7. Packing tiny items

When each item is a single lookup (one claim, one URL status, one config key), pack them:

```
pack size p = 3..10 items per brief      spawns = ceil(N / p)
choose p so that one brief stays within about 0.6 x maxTurns of the agent
fact-checker (maxTurns 180 in config/models.json): about 6-12 claims per brief
```

Each packed brief returns one JSON block per item (an array). Retries then apply per pack, and a
failed pack lists all its item ids as failed.
