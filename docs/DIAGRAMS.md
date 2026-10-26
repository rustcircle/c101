# Diagrams

Mermaid diagrams of the c101 agent stack: the saved workflows, the system as a whole, the life of one
request, the guard on every spawn, web-content safety, the self-tuning loop and the image pipeline. GitHub
renders them in place; they use only `flowchart`, `sequenceDiagram` and `stateDiagram-v2`. Rendered SVG copies
of diagrams 1 and 2, [all-workflows.svg](diagrams/all-workflows.svg) and
[system-overview.svg](diagrams/system-overview.svg), are there for viewers that do not render Mermaid. Labels
follow the code they summarise (`.claude/workflows/*.js`, `stack/hooks.py`, `stack/budget.py`,
`stack/injection.py`, `stack/learn/`, `config/policy.json`); where prose and code differ, the diagrams follow the
code.

| Colour | Meaning |
|---|---|
| blue | an agent produces content |
| orange | an agent judges, verifies, critiques or rules |
| green | code decides: the workflow script or a hook computes it |
| purple | synthesis and final outputs |
| red | stop, deny or early exit |
| yellow | files, configuration and stored state |
| grey | entry points and notes |

Contents:

1. [All saved workflows in one picture](#1-all-saved-workflows-in-one-picture)
2. [System overview](#2-system-overview)
3. [Request lifecycle](#3-request-lifecycle)
4. [Guard pipeline for one spawn](#4-guard-pipeline-for-one-spawn)
5. [Web-content safety](#5-web-content-safety)
6. [Self-tuning loop](#6-self-tuning-loop)
7. [Image pipeline](#7-image-pipeline)
8. [Workflows one by one](#8-workflows-one-by-one): [swarm-run](#81-swarm-run), [fanout](#82-fanout),
   [mediate](#83-mediate), [expert-panel](#84-expert-panel), [research-sweep](#85-research-sweep),
   [review-verify](#86-review-verify), [plan-tournament](#87-plan-tournament),
   [visual-iterate](#88-visual-iterate)

## 1. All saved workflows in one picture

A saved workflow is a plain JavaScript script in `.claude/workflows/` that only the main thread can launch, with
the Workflow tool or `/<name>`; Claude Code removes the Workflow tool from every subagent, so a subagent returns
the recommendation as an Open doubt instead. Every script validates its args before it starts a single agent and,
when a required field is missing or invalid, returns `{started: false, reason, next}` with a ready-to-use example.
Once a script runs, agents only produce content (solutions, ballots, findings, claims, plans, images) and the
script computes every decision: tallies, quantiles, stop rules, dedup and coverage ledgers, so each result can be
replayed from the agents' structured returns. Each row reads left to right: who produces (blue), who judges or
verifies (orange), where the script decides and what stops it (green), and what comes out (purple).
[Section 8](#8-workflows-one-by-one) draws each workflow in more detail. Source:
[Saved workflows](reference/workflows.md#saved-workflows).

```mermaid
flowchart TB
    subgraph ENTRY["Shared entry, main thread only"]
        direction LR
        E1(["main thread, depth 0<br/>Workflow tool or /name"]):::entry
        E2{"args valid?"}:::calc
        E3[/"started: false,<br/>reason + next example,<br/>no agent started"/]:::halt
        E1 --> E2
        E2 -->|no| E3
    end

    subgraph ALL["Agents produce content, the script decides"]
        direction TB

        subgraph SW["swarm-run"]
            direction LR
            SW1["Work: a worker per<br/>shard, pipelined,<br/>re-run once if dead"]:::agent
            SW2["Normalize:<br/>file-summarizer,<br/>code parser fallback"]:::agent
            SW3{{"code: retry only<br/>the uncovered part<br/>once; exact-key<br/>dedup, coverage<br/>ledger"}}:::calc
            SW4["Merge:<br/>swarm-coordinator;<br/>none if every<br/>shard failed"]:::out
            SW1 --> SW2 --> SW3 --> SW4
        end

        subgraph FO["fanout"]
            direction LR
            FO1["Map: one agentType<br/>call per item;<br/>prompts rendered<br/>up front"]:::agent
            FO2{{"code: retry null,<br/>empty or thrown;<br/>once by default,<br/>max 3"}}:::calc
            FO3[/"results in input<br/>order, failed,<br/>skipped"/]:::out
            FO1 --> FO2 --> FO3
        end

        subgraph ME["mediate"]
            direction LR
            ME1["Solve: 3-9 diverse<br/>voters, independent"]:::agent
            ME2["Critique+Rank: the<br/>same voters rank<br/>S1..Sn blind"]:::judge
            ME3{{"code: tally the<br/>declared rule,<br/>Schulze by default;<br/>robustness checks"}}:::calc
            ME4["Debate on a<br/>near-tie: top two<br/>rebut, voters re-vote"]:::judge
            ME5["Synthesize:<br/>mediator, winner<br/>+ grafts"]:::out
            ME1 --> ME2 --> ME3 -->|clear| ME5
            ME3 -->|near-tie| ME4 --> ME5
        end

        subgraph EP["expert-panel"]
            direction LR
            EP1["Frame:<br/>expert-panel-chair,<br/>4-7 panelists"]:::agent
            EP2["Round k: panelists<br/>answer blind,<br/>in parallel"]:::agent
            EP3{{"code: median, IQR,<br/>pools, Borda; stop:<br/>convergence,<br/>stability, cap,<br/>budget"}}:::calc
            EP4["Feedback:<br/>source-summarizer,<br/>fact-checker<br/>rules on cruxes"]:::judge
            EP5["Synthesize: chair,<br/>consensus and<br/>minority report"]:::out
            EP1 --> EP2 --> EP3 -->|stop| EP5
            EP3 -->|continue| EP4 -->|packet| EP2
        end

        subgraph RS["research-sweep"]
            direction LR
            RS1["Plan:<br/>deep-researcher,<br/>sub-questions"]:::agent
            RS2["Sweep + Extract:<br/>web-searcher,<br/>paper-researcher,<br/>web-crawler,<br/>source-summarizer"]:::agent
            RS3{{"code: claim ledger,<br/>dedup; risk score<br/>picks claims"}}:::calc
            RS4["Verify:<br/>fact-checker;<br/>Critic:<br/>quality-control"]:::judge
            RS5["Synthesize:<br/>deep-researcher,<br/>cited report"]:::out
            RS1 --> RS2 --> RS3 --> RS4 -->|"dry or cap"| RS5
            RS4 -->|gaps| RS2
        end

        subgraph RV["review-verify"]
            direction LR
            RV1["Scope:<br/>file-summarizer;<br/>Find: a finder per<br/>dimension x shard"]:::agent
            RV2{{"code: dedup within<br/>2 lines, triage,<br/>cap at maxVerify"}}:::calc
            RV3["Verify: 3<br/>adversarial-verifier<br/>lenses try to refute"]:::judge
            RV4{{"code: majority<br/>confirms, else<br/>inconclusive or<br/>rejected"}}:::calc
            RV5["Report:<br/>file-summarizer"]:::out
            RV1 --> RV2 --> RV3 --> RV4 --> RV5
        end

        subgraph PT["plan-tournament"]
            direction LR
            PT1["Generate: planner<br/>or architect, one<br/>plan per angle"]:::agent
            PT2["Judge: 1-7 blind<br/>judges, 5 criteria"]:::judge
            PT3{{"code: medians x<br/>weights, Borda<br/>tie-break, grafts"}}:::calc
            PT4["Synthesize:<br/>planner merges<br/>the winner"]:::out
            PT5["Critique:<br/>plan-critic; one<br/>Revise by planner"]:::judge
            PT1 --> PT2 --> PT3 --> PT4 --> PT5
        end

        subgraph VI["visual-iterate"]
            direction LR
            VI1["Produce:<br/>image-generator,<br/>image-editor or<br/>vector-artist"]:::agent
            VI2["Review:<br/>visual-reviewer<br/>scores the rubric"]:::judge
            VI3{{"code: overall, PASS,<br/>best so far; stop:<br/>pass, max rounds,<br/>no gain twice,<br/>STOP, blocked,<br/>budget"}}:::calc
            VI4["Export, optional:<br/>layered SVG, PDF"]:::out
            VI1 --> VI2 --> VI3 -->|stop| VI4
            VI3 -->|revise| VI1
        end

        SW ~~~ FO ~~~ ME ~~~ EP ~~~ RS ~~~ RV ~~~ PT ~~~ VI
    end

    ENTRY -->|"valid: the script runs"| ALL

    classDef entry fill:#b0bec5,stroke:#37474f,color:#111
    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
```

## 2. System overview

The `delegator` is the only agent that talks to the user: it runs as the main thread at depth 0, classifies each
request and sends it down the cheapest adequate route, either a saved workflow or an Agent call into one of the
nine agent groups (63 agents, nesting up to depth 8, every spawn checked by the `pre-agent` hook of diagram 4).
Each agent lists only the MCP servers it calls: the research agents use exa, jina, spider and fetch, with
playwright for `browser-operator` and the built-in computer-use server for `computer-operator`; `tester` uses
playwright; eleven experts and `architect` use context7; the image agents and `graphic-design-expert` use the image
server. Each of these connects only while its agent runs. The exception is neural-memory: the delegator carries it,
so it runs for the whole main-thread session, and `orchestrator`, `planner`, `architect`, `debugger` and `reviewer`
share that connection. Every agent preloads the three protocol skills plus at most three role skills: method skills from the core
pack, or for an expert the hub skill of its domain pack, which indexes that pack's granular skills (144 skills in
19 install packs). Any agent at any depth can hand an Open doubt to one of the doubt resolvers, budget and depth
permitting. Source: [Agent layers](reference/overview.md#agent-layers), [docs/ARCHITECTURE.md](ARCHITECTURE.md),
[docs/MCP.md](MCP.md).

```mermaid
flowchart TB
    U(["user"]):::entry
    D["delegator<br/>main thread, depth 0"]:::entry
    WF["saved workflows<br/>main thread only"]:::calc

    subgraph SK["skills layer: 144 skills in 19 install packs"]
        direction LR
        PS["protocol skills, all:<br/>delegation-protocol,<br/>doubt-escalation,<br/>output-contract"]:::memo
        MS["method skills, core<br/>pack: mediator-voting,<br/>delphi-method, ..."]:::memo
        HS["hub skill per domain<br/>pack: rust-craft,<br/>mathematics-toolkit, ..."]:::memo
        GS["granular skills<br/>of that pack"]:::memo
        PS ~~~ GS
        MS ~~~ GS
        HS -->|indexes| GS
    end

    subgraph AG["63 agents in 9 groups; subagents run at depth 1 to 8"]
        direction TB
        ORC["Orchestration, 7<br/>(with the delegator):<br/>orchestrator, mediator,<br/>swarm-coordinator, ..."]:::agent
        PLN["Planning, 3<br/>planner, architect,<br/>plan-critic"]:::agent
        QA["Quality, 9<br/>reviewer, validator,<br/>tester, debugger, ..."]:::judge
        RES["Research, 11<br/>search, scrape, crawl,<br/>browse, papers, ..."]:::agent
        EXP["Experts, 15<br/>9 languages, CS, math,<br/>physics, graphics, ..."]:::agent
        SYN["Synthesis, 6<br/>expert-panel-chair,<br/>debate-moderator, ..."]:::out
        IMG["Image, 4<br/>image-generator,<br/>visual-reviewer, ..."]:::agent
        MET["Meta, 2<br/>stack-tuner,<br/>agent-architect"]:::agent
        ORC ~~~ QA ~~~ EXP ~~~ IMG
        PLN ~~~ RES ~~~ SYN ~~~ MET
    end

    subgraph MCP["MCP servers, per agent"]
        direction TB
        EXA["exa<br/>5 research agents"]:::store
        JIN["jina<br/>7 research agents"]:::store
        SPI["spider<br/>web-scraper,<br/>web-crawler,<br/>deep-researcher"]:::store
        FET["fetch<br/>8 research agents"]:::store
        PWR["playwright<br/>browser-operator,<br/>tester"]:::store
        CUS["computer-use,<br/>built-in<br/>computer-operator"]:::store
        C7["context7<br/>9 experts,<br/>architect"]:::store
        IMS["image<br/>image agents,<br/>graphic-design-expert"]:::store
        EXA ~~~ JIN ~~~ SPI ~~~ FET
        PWR ~~~ CUS ~~~ C7 ~~~ IMS
    end

    subgraph DB["Open doubts, from any depth"]
        direction LR
        DR["quick-researcher,<br/>deep-researcher,<br/>fact-checker"]:::judge
        DT["tester"]:::judge
        DQ["quality-control,<br/>code-quality-analyst"]:::judge
        DV["adversarial-verifier"]:::judge
        DF["file-summarizer"]:::judge
    end

    U --> D
    D -->|"Workflow tool"| WF
    D -->|"Agent tool,<br/>via pre-agent"| AG
    SK -->|"3 protocol + up to<br/>3 role skills each"| AG
    AG -->|"tool calls"| MCP
    AG -.->|"doubt escalation"| DB

    classDef entry fill:#b0bec5,stroke:#37474f,color:#111
    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef store fill:#fff59d,stroke:#f9a825,color:#111
    classDef memo fill:#eeeeee,stroke:#757575,color:#111
```

## 3. Request lifecycle

One request from start to finish, with the hook handlers in `stack/hooks.py` (run as `bin/stack hook <name>`) as
the control plane. `SessionStart` catches up on any learned values still pending (the values the learner applied at the end of the
previous session are already on disk and were loaded) and adds a status line; `UserPromptSubmit` adds the whole-tree token-budget note.
Every Agent call passes `pre-agent` (diagram 4), which prepends the `<stack-context>` header to the child's brief.
A subagent at depth n that reads the web passes `post-web` and `pre-tool` (diagram 5). The child returns the
five-section output contract and keeps long output in `.stack/out/<agent>/`. `SubagentStop` runs asynchronously,
records the effort that was in effect and ingests the session at most once a minute; `SessionEnd` detaches the
learner (diagram 6), which updates the posteriors and records the session in `history.jsonl` and, with `apply_on: "session_end"`, writes the learned values into the agent
files, for the next session to load (a running session re-reads them from its next turn). `pre-agent` records each
spawn's `maxTurns` so the limit a run was held to is known whatever happens to the file later. Every handler fails open: an error inside a hook never blocks the session, only deliberate
deny or ask decisions do. The `PreModelSwitch` guard, which keeps the main thread on its tier model, is left out.
Source: [Lifecycle of one request](reference/overview.md#lifecycle-of-one-request), [Hook wiring](reference/hooks.md#hook-wiring).

```mermaid
sequenceDiagram
    autonumber
    actor U as user
    participant H as hooks
    participant D as delegator, depth 0
    participant S as subagent, depth n
    participant W as web tool
    participant L as learner

    U->>H: bin/claude-stack starts<br/>SessionStart
    H->>L: apply pending values:<br/>maxTurns and effort in the<br/>frontmatter, changes.jsonl
    H-->>D: status line: max depth 8,<br/>missing keys, applied tuning
    U->>H: prompt<br/>UserPromptSubmit
    H-->>D: prompt + budget note:<br/>session of 10B, soft 7.5B,<br/>prompt up to 400M, soft 300M
    D->>D: classify, pick the<br/>cheapest adequate route
    D->>H: Agent call<br/>PreToolUse pre-agent
    H->>H: depth, spawn rules, taint,<br/>tokens, 128 spawns
    alt denied
        H-->>D: deny + reason: finish yourself<br/>or return an Open doubt
    else allowed
        H->>S: brief + stack-context header,<br/>per-call model and effort stripped
        S->>W: fetch, jina, exa, spider,<br/>playwright, WebFetch
        W-->>H: PostToolUse post-web<br/>scores the result
        opt score medium or high
            H-->>S: warning, agent tainted,<br/>event logged, high blocks
        end
        S->>H: Bash, file write, form typing<br/>PreToolUse pre-tool
        H-->>S: web agent: risky Bash or write<br/>denied, tainted: any risky<br/>action denied
        S-->>D: Result, Evidence, Files,<br/>Open doubts, Confidence
        S-)H: SubagentStop, async
        H-)L: record effort, ingest at most<br/>once a minute, update every<br/>30 min, no apply
    end
    D-->>U: answer in the five-section<br/>output contract
    U->>H: session ends<br/>SessionEnd
    H-)L: detached learn run
    L->>L: ingest, update, record<br/>history.jsonl; applied here,<br/>read at next load or turn
```

## 4. Guard pipeline for one spawn

What the `pre-agent` hook (PreToolUse on `Agent|Task`) does with every spawn, in the order of the code. Depth
counts from the main thread at 0, and the caller's depth comes from its `agent-<id>.meta.json`. Spawn rules come
from `config/policy.json` `spawn_rules`: a per-caller allow-list (for example `web-scraper` may call only the two
summarizers) and no orchestration agent, `expert-panel-chair` or `debate-moderator` below depth 6. A caller tainted
by flagged web content may spawn only research leaves (diagram 5). Token use is summed over the whole delegation
tree for the session and for the current prompt, and the worse of the two levels applies: below the guaranteed
floor nothing is ever throttled, `soft` tells agents to converge, `hard` leaves only the finishing agents. The
spawn counter covers the whole session. Tier enforcement strips any per-call `model` and `effort`, so every agent
runs on its tier model and learned effort. On an internal error the hook fails open and the spawn proceeds
unchanged. Source: [pre-agent](reference/hooks.md#pre-agent-depth-guard-spawn-rules-budgets-and-tier-stripping),
[Token budgets](reference/hooks.md#token-budgets), [docs/DEPTH.md](DEPTH.md).

```mermaid
flowchart TD
    A(["Agent or Task call<br/>from a caller at depth d"]):::entry
    B{"d + 1<br/>above 8?"}:::calc
    C{"spawn rule<br/>broken?"}:::calc
    T{"tainted caller,<br/>child not a<br/>research leaf?"}:::calc
    E["budget.status:<br/>whole-tree tokens,<br/>session and prompt"]:::calc
    LV{"budget level,<br/>the worse of<br/>the two?"}:::calc
    HF{"child a<br/>finishing agent?"}:::calc
    G["spawn counter + 1,<br/>whole session"]:::store
    H{"counter<br/>above 128?"}:::calc
    I{"header present<br/>or injection off?"}:::calc
    J["prepend stack-context:<br/>depth, max_depth,<br/>parent, remaining_depth,<br/>spawns_this_session,<br/>budget level, tokens,<br/>out_dir"]:::calc
    K["tiers: strip per-call<br/>model and effort;<br/>SDK runs: forced<br/>foreground"]:::calc
    L(["allow + updatedInput;<br/>main thread: note on<br/>effort drift"]):::out

    X1["deny: depth limit;<br/>do it yourself or<br/>return an Open doubt"]:::halt
    X2["deny: caller allow-list,<br/>or an orchestration<br/>agent below depth 6"]:::halt
    X5["deny; the main<br/>thread gets ask"]:::halt
    X3["deny: tokens spent;<br/>finish with what<br/>you have"]:::halt
    X4["deny: spawn budget<br/>exhausted"]:::halt
    FO["hook error:<br/>fail open,<br/>spawn unchanged"]:::memo

    A --> B
    B -->|yes| X1
    B -->|no| C
    C -->|yes| X2
    C -->|no| T
    T -->|yes| X5
    T -->|no| E --> LV
    LV -->|"ok: below soft;<br/>never throttled under<br/>2.5B session, 100M prompt"| G
    LV -->|"soft: session 7.5B+<br/>or prompt 300M+;<br/>header says converge"| G
    LV -->|"hard: session 10B+<br/>or prompt 400M+"| HF
    HF -->|"yes: file-summarizer,<br/>quality-control,<br/>validator or<br/>source-summarizer"| G
    HF -->|no| X3
    G --> H
    H -->|yes| X4
    H -->|no| I
    I -->|no| J --> K
    I -->|yes| K
    K --> L
    A -.- FO

    classDef entry fill:#b0bec5,stroke:#37474f,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
    classDef store fill:#fff59d,stroke:#f9a825,color:#111
    classDef memo fill:#eeeeee,stroke:#757575,color:#111
```

## 5. Web-content safety

Pages, search results and documents fetched from the web are untrusted, so the stack contains prompt injection
in three layers (`config/policy.json` `web_content`, `stack/injection.py`, hooks `post-web` and `pre-tool`).
Layer 1 holds whether or not anything was flagged: the agents that read web pages have no Edit or NotebookEdit,
and `pre-tool` keeps their file writes under `.stack/` and also denies them network egress, pipe-to-shell, secret
reads and `git push` from Bash. Layer 2 scores every web-tool result with weighted rules (instruction overrides,
tool-call markup, requests for secrets, smuggled characters and more): `low` passes untouched, `medium` (score 3)
adds a warning to the agent's context and logs the event (rule names, score, URL and a SHA-256, never the text),
`high` (score 6) also returns a block decision with the reason, and any flag taints the agent. Layer 3 checks the
taint before risky actions: a tainted subagent is denied, the main thread gets an ask prompt, and a tainted agent
may spawn only research leaves. The scanner is a tripwire, not a guarantee (paraphrases, other languages and text
in images get through), which is why layer 1 never depends on a flag. Source:
[Web content safety](reference/web-safety.md#web-content-safety-prompt-injection), [`stack/injection.py`](../stack/injection.py).

```mermaid
flowchart TB
    subgraph L1["Layer 1: least privilege, always on"]
        direction LR
        WA["agents that read<br/>web pages: the research<br/>agents, incl.<br/>browser-operator and<br/>computer-operator"]:::agent
        NE["no Edit,<br/>no NotebookEdit"]:::calc
        WR["writes only under<br/>.stack/; pre-tool also<br/>denies Bash egress,<br/>pipe-to-shell, secret<br/>reads, git push"]:::calc
        WA --- NE
        WA --- WR
    end

    subgraph L2["Layer 2: PostToolUse scan of web-tool results"]
        direction LR
        WT["mcp__fetch, mcp__jina,<br/>mcp__exa, mcp__spider,<br/>mcp__playwright,<br/>WebFetch, WebSearch,<br/>optional web servers"]:::entry
        SC{{"post-web:<br/>score for injection<br/>patterns"}}:::calc
        LO["low:<br/>passes"]:::out
        MD["medium, score 3+:<br/>warning in context,<br/>event logged"]:::judge
        HI["high, score 6+:<br/>also a block decision<br/>with the reason"]:::halt
        TA[("agent marked<br/>tainted")]:::store
        WT --> SC
        SC --> LO
        SC --> MD --> TA
        SC --> HI --> TA
    end

    subgraph L3["Layer 3: PreToolUse taint guard"]
        direction LR
        RK["risky: Bash with network<br/>egress, pipe-to-shell or<br/>secret reads, git push,<br/>writes outside .stack/,<br/>Playwright typing or<br/>form filling"]:::memo
        RA{"tainted agent,<br/>risky action?"}:::calc
        SUB["subagent:<br/>deny"]:::halt
        MT["main thread:<br/>ask the user"]:::judge
        PA["otherwise:<br/>allowed"]:::out
        SP["its spawns:<br/>research leaves only"]:::memo
        RK -.- RA
        RA -->|"yes, subagent"| SUB
        RA -->|"yes, main thread"| MT
        RA -->|no| PA
        RA -.- SP
    end

    L1 -->|"they read pages through"| L2
    L2 -->|"taint state"| L3

    classDef entry fill:#b0bec5,stroke:#37474f,color:#111
    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
    classDef store fill:#fff59d,stroke:#f9a825,color:#111
    classDef memo fill:#eeeeee,stroke:#757575,color:#111
```

## 6. Self-tuning loop

After each session (and every 30 minutes during a long one) the learner updates what each agent's `maxTurns` and
`effort` should be, given what its runs actually needed; the end of the session writes it (`apply_on`), so the next session loads it (a running one re-reads it from its next turn) and agent
files never change while a session runs. Ingest turns the transcripts into one record per agent run. Update
fits per-agent posteriors: capped runs count as right-censored ("needed at least the cap"), so a cap that is too
low cannot lock itself in, and old runs are down-weighted by a forgetting factor chosen per agent by prequential
score. Apply writes a recommendation into the agent's frontmatter only with enough evidence and inside the bounds,
step limits and hysteresis of `config/learning.json`, and appends every change to `changes.jsonl`, so
`git diff .claude/agents` shows exactly what the learner did. The token windows feed `budgets.json`; the global
token-budget limits are only reported unless `token_budget.learn_global` is `apply`. Source:
[Bayesian self-tuning](reference/learning.md#bayesian-self-tuning), [docs/LEARNING.md](LEARNING.md).

```mermaid
flowchart TB
    S(["sessions: main thread<br/>and every subagent"]):::entry
    T[("transcripts:<br/>session.jsonl,<br/>subagents/agent-ID.jsonl")]:::store

    subgraph TR["triggers"]
        T1["SubagentStop, async:<br/>ingest at most once<br/>a minute; update<br/>every 30 min"]:::calc
        T2["SessionEnd:<br/>detached learn run:<br/>ingest, update, history"]:::calc
        T3["Agent SDK runner:<br/>run_after_session"]:::calc
    end

    I["ingest: one record<br/>per agent run:<br/>tool_rounds, capped,<br/>effort, tokens, ctx_peak"]:::calc
    O[("obs/SESSION.json")]:::store

    subgraph UP["update: Bayesian posteriors per agent"]
        P1["maxTurns: censored<br/>log-normal on a<br/>48 x 28 grid; forgetting<br/>factor by prequential<br/>score"]:::calc
        P2["effort: Dirichlet over<br/>output-token bands,<br/>Beta(1, 4) failure rate"]:::calc
        P3["token windows:<br/>log-normal<br/>q05, q50, q95"]:::calc
    end

    R[("recommendations.json,<br/>budgets.json")]:::store
    HJ[("history.jsonl:<br/>one line per session")]:::store
    T4["SessionEnd (or catch-up at<br/>SessionStart, learn start)"]:::calc
    A{{"apply within bounds:<br/>n_eff 3+, 5+ for effort;<br/>per-agent bounds;<br/>step x2 or one level;<br/>maxTurns change 10%+"}}:::calc
    F["agent frontmatter:<br/>maxTurns, effort"]:::out
    C[("changes.jsonl<br/>audit log")]:::store

    S --> T3
    S --> T2
    S --> T1
    S --> T
    T3 --> I
    T2 --> I
    T1 --> I
    T --> I
    I --> O
    O --> P3
    O --> P2
    O --> P1
    P3 --> R
    P2 --> R
    P1 --> R
    R --> HJ
    R --> A
    T4 --> A
    A --> F
    A --> C
    F -->|"read when the next<br/>session starts"| S

    classDef entry fill:#b0bec5,stroke:#37474f,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef store fill:#fff59d,stroke:#f9a825,color:#111
```

## 7. Image pipeline

The `image` MCP server (`stack_mcp/image_router/`, started by `bin/mcp-run bin/image-router`) gives each
operation its own endpoint, key and model from `~/.claude/stack.env`, with no fallbacks: an operation's tool is
listed only while that operation is configured (the env file is read at call time and watched), and the local
tools are always listed. The adapter is chosen from the URL host or `IMAGE_<OP>_API`. Post-processing restores
fidelity whatever the provider returned, and every output lands in `.stack/images/<date>/` with a JSON sidecar
that never contains keys. The producer agents send their candidates to `visual-reviewer`, which scores them
against the brief with a weighted rubric and returns PASS, REVISE with numbered revisions, or STOP; the loop ends
after round 4 at the latest. Layered SVG and layered PDF exports come last. Source:
[The image server](reference/mcp.md#the-image-server),
[The visual-reviewer agent](reference/agents.md#the-visual-reviewer-agent), [docs/MCP.md](MCP.md).

```mermaid
flowchart TB
    PR["producer:<br/>image-generator,<br/>image-editor,<br/>vector-artist"]:::agent
    ENV[("stack.env, one set<br/>per operation:<br/>IMAGE_OP_URL, _KEY,<br/>_MODEL for GEN, REF,<br/>EDIT, TRANSPARENT,<br/>SEGMENT, BG_REMOVAL,<br/>UPSCALE, VECTOR, TRACE")]:::store

    subgraph SRV["image MCP server"]
        CF{"operation<br/>configured?"}:::calc
        LT["its tool is listed:<br/>image_generate,<br/>image_edit, ..."]:::out
        HD["not listed, no<br/>fallback; status names<br/>the missing variables"]:::halt
        LO["always listed:<br/>image_ops_status,<br/>image_info, svg_render,<br/>export_pdf, ..."]:::memo
        CF -->|yes| LT
        CF -->|no| HD
    end

    subgraph ADP["adapter, from the URL host or _API"]
        A1["openrouter"]:::calc
        A2["opper"]:::calc
        A3["fal"]:::calc
        A4["openai"]:::calc
        A5["local: trace,<br/>upscale"]:::calc
    end

    FP["fidelity fixes:<br/>pixels outside the<br/>mask kept, alpha moved<br/>onto the original,<br/>binary masks, exact<br/>upscale factor"]:::calc
    OUT[(".stack/images/DATE/<br/>output + JSON sidecar,<br/>never keys")]:::store
    VR["visual-reviewer:<br/>scores 0-10 per<br/>criterion; PASS needs<br/>overall 8+, each<br/>applicable one 6+"]:::judge
    V{"verdict, at most<br/>4 rounds"}:::calc
    FIN["best attempt<br/>+ review trail"]:::out
    EXP["export: svg_layerize or<br/>layers_compose to a<br/>layered SVG; export_pdf<br/>to a layered PDF, one<br/>OCG per layer"]:::out

    PR -->|"calls a listed tool"| LT
    ENV -->|"read at call time"| CF
    LT --> A5
    LT --> A4
    LT --> A3
    LT --> A2
    LT --> A1
    A5 --> FP
    A4 --> FP
    A3 --> FP
    A2 --> FP
    A1 --> FP
    FP --> OUT --> VR --> V
    V -->|"REVISE: numbered<br/>revisions"| PR
    V -->|"PASS, or STOP: round 4,<br/>budget, plateau,<br/>same defect twice"| FIN
    FIN -->|"layered output asked"| EXP

    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
    classDef store fill:#fff59d,stroke:#f9a825,color:#111
    classDef memo fill:#eeeeee,stroke:#757575,color:#111
```

## 8. Workflows one by one

One diagram per saved workflow, with the stages, caps and stop rules each script implements. Each starts at the
shared entry of diagram 1: the args are validated before any agent starts.

### 8.1 swarm-run

One worker per shard with a fixed output contract, normalised per shard, one retry of exactly the uncovered
remainder, then exact-key dedup and a coverage ledger in code and a `swarm-coordinator` merge. Workers return
`SHARD <id> STATUS <ok|partial|failed> COVERED <n>/<m> ITEMS <k>` followed by `ITEM`, `UNCOVERED` and `XSHARD`
lines. A dead worker is re-run once with the same brief, which uses up that shard's retry. Coverage from a
remainder retry adds up (the units are disjoint); a whole-shard retry takes the better attempt, never the sum. The
nominal agent count is two per shard plus one merge. Source: [swarm-run](reference/workflows.md#swarm-run).

```mermaid
flowchart TD
    A{"task and<br/>shards valid?"}:::calc
    X[/"started: false"/]:::halt
    B{{"shards: empty briefs<br/>rejected, ids s01..,<br/>duplicates renamed,<br/>over maxShards capped,<br/>150 by default, max 165"}}:::calc

    subgraph PIPE["pipeline per shard, about 16 agents at a time"]
        direction TB
        W["Work: one worker of<br/>agentType, by default<br/>general-purpose on<br/>sonnet; null, empty or<br/>thrown: same brief<br/>re-run once"]:::agent
        N["Normalize:<br/>file-summarizer writes<br/>results/ID.json;<br/>code parser fallback"]:::agent
        RQ{"not ok, retry on,<br/>not re-run yet,<br/>budget 40k+?"}:::calc
        RT["Retry once: failed with<br/>8+ uncovered units is<br/>split in two, else one<br/>retry of the uncovered<br/>units; effort +1 level"]:::agent
        CB{{"combine: remainder<br/>adds coverage,<br/>whole-shard retry<br/>takes the max"}}:::calc
        REC["shard record"]:::out
        W --> N --> RQ
        RQ -->|yes| RT --> CB --> REC
        RQ -->|no| REC
    end

    D{{"barrier, then code:<br/>exact-key dedup, keep<br/>highest severity, union<br/>of shards; coverage<br/>ledger, c/t units"}}:::calc
    F{"every shard<br/>failed?"}:::calc
    XF[/"merged: null,<br/>no merge"/]:::halt
    XS["XSHARD follow-ups:<br/>a worker per target<br/>named by 3+ doubts,<br/>at most 5, budget 40k+"]:::agent
    Z{"no items and<br/>no follow-up<br/>answers?"}:::calc
    ZI[/"ledger inline,<br/>no merge agent"/]:::out
    M["Merge:<br/>swarm-coordinator,<br/>semantic dedup,<br/>conflicts, merged.json,<br/>ledger.md, spot-check"]:::out
    MF[/"merge failed:<br/>code dedup returned"/]:::halt
    O[/"return: merged,<br/>perShard, failed,<br/>coverage"/]:::out

    A -->|no| X
    A -->|yes| B --> PIPE
    PIPE --> D --> F
    F -->|yes| XF
    F -->|no| XS --> Z
    Z -->|yes| ZI
    Z -->|no| M --> O
    M -.->|fails| MF

    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
```

### 8.2 fanout

A generic concurrent map: one agent of one type per item, prompt rendered from a template, with optional JSON
schema results and retries of null, empty or failed calls. Every prompt is rendered before any agent starts, so a
template mistake costs nothing: a template without the item placeholder gets the item appended under `ITEM:` (a
warning), and a field path that is empty for every item stops the run. Each prompt tells the agent to write its
full deliverable to a numbered file in the output directory. The agent count lies between `N` and
`N x (1 + retry)`. Source: [fanout](reference/workflows.md#fanout).

```mermaid
flowchart TD
    A{"args<br/>valid?"}:::calc
    X[/"started: false,<br/>reason + next"/]:::halt
    R{{"render every prompt<br/>up front; no item<br/>placeholder: item<br/>appended, warning"}}:::calc
    P{"a field path<br/>empty for<br/>every item?"}:::calc
    C{{"cap: maxItems 400<br/>by default, max 900,<br/>and at most<br/>990 / (1 + retry)"}}:::calc
    SK[/"over the cap:<br/>not run, returned<br/>in skipped"/]:::halt

    subgraph PIPE["pipeline per item"]
        direction TB
        M["Map: one agentType<br/>call; model and effort<br/>only for<br/>general-purpose"]:::agent
        E{"null, empty<br/>or threw?"}:::calc
        Q{"retry left and<br/>budget 20k+?"}:::calc
        RT["Retry: the same<br/>prompt; retry 1 by<br/>default, max 3"]:::agent
        OK["result"]:::out
        FL["failed,<br/>with the reason"]:::halt
        M --> E
        E -->|no| OK
        E -->|yes| Q
        Q -->|yes| RT --> E
        Q -->|no| FL
    end

    O[/"return in input order:<br/>results, failed,<br/>skipped, warnings;<br/>text over 3000 chars<br/>clipped, full text<br/>on disk"/]:::out

    A -->|"no: items, agentType,<br/>template or schema"| X
    A -->|yes| R --> P
    P -->|yes| X
    P -->|no| C --> PIPE --> O
    C -.-> SK

    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
```

### 8.3 mediate

Diverse voters solve independently, then rank the anonymised solutions blind; the rule declared before solving
(Schulze by default) is tallied in code together with every other rule, a no-self run and a leave-one-out run per
ballot. A near-tie triggers one debate round, and `mediator` writes the final answer from the winner with grafts
from runner-up strengths. Labels `S1..Sn` follow the order of an FNV-1a hash of the normalised answer and
arguments, so a label never reveals its author. Near-tie thresholds are 0.2 for plurality, approval and Schulze
and 0.1 for Borda and the log pool. The agent count is `2V + 1`, plus `2 + V` with a debate. Source:
[mediate](reference/workflows.md#mediate).

```mermaid
flowchart TD
    A{"problem, method,<br/>3-9 voters valid?"}:::calc
    X[/"started: false"/]:::halt
    S["Solve: every voter in<br/>parallel, no spawning:<br/>answer, arguments,<br/>assumptions, failure<br/>modes, confidence"]:::agent
    S2{"2+ solutions?"}:::calc
    XS[/"end: under 2<br/>solutions or ballots,<br/>no vote"/]:::halt
    AN{{"code: anonymise roles,<br/>agent and model names;<br/>labels S1..Sn<br/>in hash order"}}:::calc
    CR["Critique+Rank: each<br/>voter, rotated order:<br/>ranking, approvals,<br/>P(best), strength and<br/>flaw per label"]:::judge
    B2{"2+ ballots?"}:::calc
    T{{"code: tally the<br/>declared rule: schulze,<br/>borda, plurality,<br/>approval or logpool;<br/>every other rule,<br/>no-self, leave-one-out"}}:::calc
    NT{"near-tie?"}:::calc
    NR["near-tie when: a tie,<br/>small margin, no-self<br/>winner differs, no<br/>Condorcet winner, small<br/>pairwise margin, LOO<br/>stability below 1"]:::memo
    DB{"debate on,<br/>budget 60k+,<br/>runner-up?"}:::calc
    RB["Debate: the two<br/>top authors rebut,<br/>300 words at most"]:::judge
    RV["every counted voter<br/>re-votes: prefer,<br/>p_prefer"]:::judge
    PW{{"code: weighted pairwise<br/>majority, logpool: a<br/>geometric pool; margin<br/>below 0.2 or one flip:<br/>STILL NEAR-TIE"}}:::calc
    DS{{"code: dissent: the<br/>winner ranked last,<br/>P below 1/n, minority<br/>first choices"}}:::calc
    SY["Synthesize: mediator<br/>runs tally.py, grafts<br/>runner-up strengths,<br/>writes report.md"]:::out
    O[/"return: winner,<br/>ranking, margin, tally,<br/>debate, dissent, final"/]:::out

    A -->|no| X
    A -->|yes| S --> S2
    S2 -->|no| XS
    S2 -->|yes| AN --> CR --> B2
    B2 -->|no| XS
    B2 -->|yes| T --> NT
    NT -.- NR
    NT -->|no| DS
    NT -->|yes| DB
    DB -->|no| DS
    DB -->|yes| RB --> RV --> PW --> DS
    DS --> SY --> O

    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
    classDef memo fill:#eeeeee,stroke:#757575,color:#111
```

### 8.4 expert-panel

A Delphi panel: anonymous independent answers, feedback statistics computed in code, revision rounds until
convergence or stable dissent, then a chair synthesis with an explicit minority report. The question kind decides
the statistics and the stop rules: `quantity` converges when the relative IQR of the P50s is at most 0.25,
`probability` when the IQR is at most 0.10, `choice` when the modal first-choice share reaches 0.75; stability from
round 2 means the median (or the Borda leader) barely moved and at most one panelist moved materially; `open`
stops on stability alone. Rounds default to 3 (at most 4), and no new round starts below 60k tokens when a budget
is set. A shrinking spread with fewer than two new reasons is labelled convergence by conformity. Source:
[expert-panel](reference/workflows.md#expert-panel).

```mermaid
flowchart TD
    A{"question<br/>given?"}:::calc
    X[/"started: false"/]:::halt
    FR["Frame:<br/>expert-panel-chair,<br/>unless frame is false<br/>and 3+ experts given:<br/>resolvable question,<br/>kind, options,<br/>4-7 panelists"]:::agent
    FD{"chair doubt,<br/>no force; or choice<br/>with under 2<br/>options?"}:::calc
    XF[/"started: false,<br/>proposed question"/]:::halt
    PN{{"panel: the caller's 3+,<br/>else the chair's 3+,<br/>else the default five;<br/>labels P1..Pn"}}:::calc
    BG{"round 2+ and<br/>budget under<br/>60k?"}:::calc
    R["Round k: every panelist<br/>in parallel, blind,<br/>5 tool calls at most:<br/>answer, 3 arguments,<br/>cruxes; later rounds:<br/>revise or hold"]:::agent
    N3{"round 1 with<br/>under 3<br/>answers?"}:::calc
    XN[/"completed: false"/]:::halt
    ST{{"code, by kind:<br/>quantity: median and<br/>IQR of P50s, pools;<br/>probability: median,<br/>IQR, log-odds pool;<br/>choice: first choices,<br/>Borda"}}:::calc
    CS{"checkStop:<br/>convergence,<br/>stability or<br/>round cap?"}:::calc
    FB["Feedback:<br/>source-summarizer<br/>clusters 7+ arguments;<br/>fact-checker rules on<br/>up to 3 cruxes"]:::judge
    PK{{"code: anonymous packet:<br/>statistics, arguments<br/>above and below the<br/>median, cruxes, rulings"}}:::calc
    HM{{"code: herding check,<br/>minority, stable<br/>dissent"}}:::calc
    SY["Synthesize:<br/>expert-panel-chair,<br/>report.md, rounds.md;<br/>confidence earned,<br/>split or conformist"]:::out

    A -->|no| X
    A -->|yes| FR --> FD
    FD -->|yes| XF
    FD -->|no| PN --> BG
    BG -->|no| R --> N3
    N3 -->|yes| XN
    N3 -->|no| ST --> CS
    CS -->|no| FB --> PK -->|next round| BG
    CS -->|yes| HM
    BG -->|"yes: stop, budget"| HM
    HM --> SY

    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
```

### 8.5 research-sweep

Plan, sweep each sub-question across modalities, extract cited claims, deduplicate and fact-check them in code,
loop a completeness critic until dry, then write a cited report. The depth sets the caps: `quick` runs 4
sub-questions over web and papers with 1 critic round and 8 claim checks, `standard` 6 sub-questions with crawling,
2 critic rounds and 20 checks, `exhaustive` 10 sub-questions, 4 critic rounds and 50 checks through two lenses.
Contradicted claims never appear as fact in the report, disputed claims show both sides, and single-origin key
claims and stale claims are flagged. Source: [research-sweep](reference/workflows.md#research-sweep).

```mermaid
flowchart TD
    A{"question<br/>given?"}:::calc
    X[/"started: false"/]:::halt
    PL["Plan: deep-researcher,<br/>4 searches at most:<br/>MECE sub-questions with<br/>modalities and queries"]:::agent
    CU{{"code: sort by priority,<br/>cut to the depth cap,<br/>cut ones become gaps;<br/>plan failed: one<br/>sub-question"}}:::calc

    subgraph SWP["pipeline per sub-question"]
        direction TB
        S1["search: web-searcher,<br/>Exa and Jina, and<br/>paper-researcher on<br/>arXiv and SSRN"]:::agent
        S2["crawl: web-crawler<br/>with Spider on the top<br/>domains, standard and<br/>exhaustive only"]:::agent
        S3["extract:<br/>source-summarizer:<br/>atomic cited claims,<br/>gaps, contradictions"]:::agent
        S1 --> S2 --> S3
    end

    LD{{"code, barrier: claim<br/>ledger; merge on equal<br/>numbers and Jaccard<br/>0.72+; origins =<br/>distinct domains"}}:::calc
    RK{{"code: risk = 3 key<br/>+ 2 quantitative + 2 one<br/>origin + 1 volatile + 2<br/>contradiction; check key<br/>claims or risk 3+"}}:::calc
    VF["Verify: fact-checker,<br/>primary-source lens,<br/>plus counter-evidence<br/>at exhaustive"]:::judge
    VC{{"code: verdicts combined:<br/>supported, partial,<br/>disputed, contradicted,<br/>unverifiable; staleness"}}:::calc
    BU{"critic round<br/>left, budget<br/>150k+?"}:::calc
    CR["Critic: quality-control<br/>reads coverage per<br/>sub-question, returns<br/>gaps with severity"]:::judge
    DR{"dry? no fresh<br/>non-minor gap,<br/>or verdict dry, no<br/>critical gap"}:::calc
    GQ{{"code: top gaps become<br/>sub-questions G r.i;<br/>verify cap max(2,<br/>ceil(cap / 3))"}}:::calc
    SY["Synthesize:<br/>deep-researcher writes<br/>claims.md, sources.md,<br/>the cited report"]:::out
    O[/"return: report path,<br/>key findings, flagged<br/>claims, gaps, stats"/]:::out

    A -->|no| X
    A -->|yes| PL --> CU --> SWP --> LD --> RK --> VF --> VC --> BU
    BU -->|yes| CR --> DR
    DR -->|no| GQ -->|"sweep, merge, verify"| SWP
    DR -->|yes| SY
    BU -->|no| SY
    SY --> O

    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
```

### 8.6 review-verify

Scope the target, run one finder per dimension and shard, deduplicate, then let `votes` (default 3, always odd)
adversarial verification lenses try to refute each finding. A finding survives only when a majority of lenses
confirm it. A crashed verifier never counts as a refutation: a finding whose confirmations plus failed lenses
reach the majority is inconclusive, not rejected. The lens set comes from the finding's most specialised
dimension (security, then performance, concurrency, correctness, and so on). The final severity is the median of
the confirming verifiers' severities. The agent count is `1 + dimensions x shards + verified x votes`, plus one
report agent. Source: [review-verify](reference/workflows.md#review-verify).

```mermaid
flowchart TD
    A{"target<br/>given?"}:::calc
    X[/"started: false"/]:::halt
    SC["Scope: file-summarizer<br/>resolves range, commit,<br/>path or worktree to<br/>files with churn; skips<br/>generated, lock, binary"]:::agent
    UR{"target<br/>unresolved?"}:::calc
    NF{"no files?"}:::calc
    EM[/"completed early:<br/>no files or<br/>no findings"/]:::out
    SH{{"code: shards by path,<br/>shardLines or 30 files;<br/>grow x1.5 while shards<br/>x dimensions exceed<br/>maxFinders"}}:::calc
    FD["Find: one finder per<br/>dimension x shard:<br/>reviewer, or<br/>security-auditor for<br/>security, code-optimizer<br/>for performance"]:::agent
    DD{{"code, barrier: no<br/>scenario, no finding;<br/>merge in one file within<br/>2 lines, Jaccard 0.5+"}}:::calc
    TR{{"code: triage: under<br/>minSeverity unverified;<br/>sort, cap at maxVerify,<br/>40 by default"}}:::calc
    VF["Verify per finding:<br/>votes lenses, default 3,<br/>each an<br/>adversarial-verifier<br/>told to refute; default<br/>refuted:insufficient"]:::judge
    DC{"confirms reach<br/>floor(votes/2)<br/>+ 1?"}:::calc
    CF["confirmed: severity<br/>= median of the<br/>confirmers, ranked"]:::out
    IC{"confirms +<br/>failed lenses<br/>reach it?"}:::calc
    IN["inconclusive"]:::judge
    RJ["rejected"]:::halt
    LE{{"refuted:misattributed<br/>with a true cause:<br/>a new lead"}}:::calc
    RP["Report:<br/>file-summarizer writes<br/>report.md unless<br/>outFile is false"]:::out

    A -->|no| X
    A -->|yes| SC --> UR
    UR -->|yes| X
    UR -->|no| NF
    SC -.->|"scope failed:<br/>unsharded"| FD
    NF -->|yes| EM
    NF -->|no| SH --> FD --> DD
    DD -->|"no findings"| EM
    DD --> TR --> VF --> DC
    DC -->|yes| CF
    DC -->|no| IC
    IC -->|yes| IN
    IC -->|no| RJ
    CF --> RP
    IN --> RP
    RJ --> RP
    VF -.-> LE -.-> RP

    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
```

### 8.7 plan-tournament

One generator per strategic angle writes a complete plan, blind judges score every plan, the ranking is computed
in code, and the winner is merged with grafts, red-teamed once and revised once. The default angles are
mvp-first, risk-first, performance-first and user-first; the default weights are feasibility 0.25, risk 0.2, cost
0.15, verifiability 0.2 and completeness 0.2. Judge `j` sees the candidates rotated by `j` (reversed for odd `j`)
with strategy names stripped. If synthesis fails, the winner's own file is returned unmerged and not revised. The
agent count is `angles + judges + 2`, plus one when revised. Source:
[plan-tournament](reference/workflows.md#plan-tournament).

```mermaid
flowchart TD
    A{"goal and 2+<br/>distinct angles?"}:::calc
    X[/"started: false"/]:::halt
    SL{{"code: systemLevel<br/>given or inferred;<br/>generator: architect<br/>if system-level,<br/>else planner"}}:::calc
    GN["Generate, barrier:<br/>one generator per<br/>angle, 2-6; plans A..F<br/>in planning-dag form,<br/>strategy never named"]:::agent
    G2{"2+ plans?"}:::calc
    XG[/"completed: false"/]:::halt
    JD["Judge: 1-7 blind judges<br/>(plan-critic,<br/>quality-control,<br/>architect, ...) score<br/>1-10 on 5 criteria,<br/>name a fatal flaw"]:::judge
    AG{{"code: median per<br/>criterion, weighted<br/>total, Borda, spread;<br/>order: weighted,<br/>Borda, fewer fatal<br/>flaws, spread"}}:::calc
    FL{{"code flags: close call<br/>under 0.5, winner flawed<br/>for over half, spread<br/>over 2; graft pool 12,<br/>16 on a close call"}}:::calc
    SY["Synthesize: planner<br/>merges the winner with<br/>grafts, fixes fatal<br/>flaws: plan.md,<br/>plan.json, scores.md"]:::out
    CR["Critique: plan-critic:<br/>issues blocker, major,<br/>minor; verdict ship,<br/>revise or rethink"]:::judge
    RQ{"blocker, major<br/>or not ship,<br/>synthesis ok?"}:::calc
    RV["Revise once: planner<br/>keeps plan-v1.md, fixes<br/>every blocker and<br/>major, revision log"]:::out
    O[/"return: plan path,<br/>ranking, scores,<br/>critique, needs_rethink<br/>on a rethink verdict"/]:::out

    A -->|no| X
    A -->|yes| SL --> GN --> G2
    G2 -->|no| XG
    G2 -->|yes| JD --> AG --> FL --> SY --> CR --> RQ
    RQ -->|yes| RV --> O
    RQ -->|no| O

    classDef agent fill:#90caf9,stroke:#1565c0,color:#111
    classDef judge fill:#ffcc80,stroke:#e65100,color:#111
    classDef calc fill:#a5d6a7,stroke:#2e7d32,color:#111
    classDef out fill:#ce93d8,stroke:#6a1b9a,color:#111
    classDef halt fill:#ef9a9a,stroke:#c62828,color:#111
```

### 8.8 visual-iterate

Produce or edit a raster or vector deliverable, have `visual-reviewer` score it against the brief, hand its
revision instructions to the next round, and keep the best attempt until the rubric passes. The producer is fixed
by `kind` and `mode`: `image-generator` (image, generate), `image-editor` (image, edit), `vector-artist` (vector).
The workflow recomputes the weighted overall with the profile fixed in round 1, and PASS needs both the rubric
(overall at the threshold, default 8, every applicable criterion at 6 or more, no blocker) and the reviewer's own
PASS. A round improves only when there is no best yet, when it passes where the best did not, or when it raises
the best overall by at least 0.3; two non-improving rounds in a row stop the loop. An unconfigured operation stops
the run at once with an Open doubt naming the `IMAGE_<OP>_URL`, `_KEY` and `_MODEL` variables, never a fallback.
Source: [visual-iterate](reference/workflows.md#visual-iterate).

```mermaid
stateDiagram-v2
    state "Validate args, pick the producer" as Validate
    state "Produce: 1-3 candidates" as Produce
    state "Review: visual-reviewer scores" as Review
    state "Score in code: overall, PASS, best so far" as Score
    state "Export: layered SVG, layered PDF" as Export
    state "Return the best attempt and the trail" as Done
    state roundGate <<choice>>
    state afterProduce <<choice>>
    state decide <<choice>>
    state exportGate <<choice>>

    [*] --> Validate
    Validate --> [*] : invalid, started false
    Validate --> roundGate : valid
    roundGate --> Produce : next round
    roundGate --> exportGate : budget under 150k
    Produce --> afterProduce
    afterProduce --> Review : candidate paths
    afterProduce --> decide : failed or no paths
    afterProduce --> exportGate : blocked, missing IMAGE env
    Review --> Score : scores, verdict, revisions
    Review --> decide : review failed
    Score --> decide
    decide --> exportGate : pass, STOP, 2 rounds without gain, max rounds
    decide --> roundGate : else revise
    exportGate --> Export : layered or pdf asked, reviewed best, not blocked, 60k left
    exportGate --> Done : otherwise
    Export --> Done
    Done --> [*]
```
