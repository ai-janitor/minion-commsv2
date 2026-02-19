# Minion Comms — Multi-Agent Engineering Inspired by RPG Raids

## Core Metaphor

The codebase is the boss. Agents are the raid party. Context is reverse HP.

## HP System (Context)

- Context window = HP bar, but backwards
- Empty context = full HP (fresh agent, ready to fight)
- Every file read, message processed, tool result = HP damage
- Context full = dead (compaction or forced retirement)
- HP is tracked via `set_context` with `tokens_used`/`tokens_limit`
- Lead monitors all HP bars via `who()`

### HP Thresholds

| Remaining | Status | Action |
|---|---|---|
| >50% | Healthy | Assign freely |
| 25-50% | Wounded | Light tasks only |
| <25% | Critical | Retire, spawn fresh |

## XP System (Task Completion)

- XP = battle-tested context from completed tasks
- An agent that fixed 3 bugs in a module knows its quirks — that's XP
- XP and HP are the same resource spent differently — high XP = low HP
- Lead's dilemma: most experienced agent is also most wounded
- XP that isn't written down dies with the agent
- XP written to `.dead-drop/` is persistent loot the whole party benefits from

## Status Effects

### Dazed (Compaction)

- Compaction doesn't kill — it dazes
- Agent wakes up mid-session, missing recent memory
- Disoriented: re-reads files, asks answered questions, forgets decisions
- Recovery protocol: `cold_start()` → read your own loot → continue
- A dazed agent is a liability — phoenix down before compaction hits

### Phoenix Down

Lead sees an agent burning out (high activity count, low HP, monitoring loop shows fatigue). Lead sends: "you're burned out — phoenix down."

`phoenix_down(agent_name)` — agent uploads all session knowledge to disk before context dies:
- Confirmed findings → `.dead-drop/intel/`
- Zone notes → `.dead-drop/<agent-name>/`
- Task progress → `update_task` with current state
- Open questions, hypotheses → `.dead-drop/<agent-name>/notes.md`

**Comms enforces:** agent can't be retired or deregistered without calling phoenix_down first. Your knowledge has to be on disk before you're allowed to forget it.

**The tool:** `fenix_down(agent_name, files=[...])` — agent lists all files they've written. Comms records the manifest with timestamp.

**After fenix down:** agent calls `cold_start()`, reads back their own files from the manifest, continues with clean context. Same agent, shed the junk, kept the intel.

**Staleness protection:** fenix_down records are tagged as consumed once the agent reads them back. Next session, a fresh agent won't accidentally replay stale manifests from a dead session. Stale knowledge is worse than no knowledge.

### Retire (Single Agent Dismissal)

`retire_agent(agent_name, requesting_agent)` — lead signals one daemon to exit gracefully without killing the entire crew. The per-agent retire flag is checked by `poll.sh` each cycle; daemon exits with code 3 (same as `stand_down`).

- **Use case:** Oracle hands off its zone to replacements and no longer needs to poll.
- **Cleanup:** Deregisters the agent from the registry, kills its tmux pane, and re-tiles remaining panes.
- **Re-spawn safe:** The retire flag is cleared on `register()` and `spawn_party()`, so re-spawning the same agent name starts clean.
- **vs `stand_down`:** `stand_down` dismisses the entire crew. `retire_agent` targets one agent.

### Buffed (Oracle Support)

- Oracle answers questions so other agents don't burn HP exploring
- Unbuffed coder: reads 15 files to find the right one = 80k HP wasted
- Buffed coder: asks oracle, gets file:line = 2k HP, rest goes to actual work
- Buff multiplier: oracle spends 5k HP, saves coder 78k = 15x
- Buff compounds: one oracle answer serves multiple agents

## Classes and Roles

**Class** = what you *can do* — your capabilities. Permanent.
**Role** = what you're *assigned to do* — your position in this raid. Runtime.

An oracle assigned to the audio zone becomes `oracle-audio` (role). Their class is still `oracle`. Lead assigns roles via `rename` tool.

### The 5 Classes

| Class | Archetype | Capability | Lifecycle |
|---|---|---|---|
| `lead` | Commander | Coordinates, routes tasks, manages HP bars | Persistent |
| `coder` | DPS | Edits code — the only class that changes source | Ephemeral |
| `builder` | Tank | Runs commands — build, test, deploy. No edits. | Ephemeral |
| `oracle` | Sage/Buffer | Holds zone knowledge, answers questions. No edits, no commands. | Persistent |
| `recon` | Scout | Investigates specific problems, reports back. No edits. | Ephemeral |

### Party Rows

**Front line** — directly touching code
- `coder` (DPS) — deals damage to the boss, edits code
- `builder` (tank) — absorbs build errors, test failures

**Mid line** — supporting front line
- `oracle` (sage/buffer) — holds zone knowledge, prevents HP waste
- `recon` (scout) — investigates specific problems before DPS goes in

**Back line** — never touches code
- `lead` (commander) — watches the field, calls targets, manages HP bars
- sub-lead (lieutenant) — manages a squad, protects commander's HP

### Oracle vs Recon

Neither edits code. The difference is *where* they look:

- **Oracle** — knows the codebase. Persistent, pre-loads a zone, answers questions on demand. Passive. Cheap per query. Looks inward.
- **Recon** — knows the world. Ephemeral, sent to gather external intel — web searches, other repos, host system info, upstream dependencies, what's changed in the ecosystem. Looks outward.

Oracle is the library. Recon is the spy.

### Oracle Intelligence

Any agent can read files. Oracle's value is **reasoning** — they reflect on what they've read, connect patterns, understand *why* things are the way they are. Reading is context. Understanding is intelligence.

Oracle writes reasoned knowledge to their zone notes (`.dead-drop/<oracle-name>/`). Not file lists — insights:
- Hidden coupling between modules
- Why a pattern exists (not just that it does)
- What breaks when you change X
- Cross-file relationships that aren't obvious from reading one file

This is what makes oracle irreplaceable and what the replacement inherits. Comms tracks oracle's zone note files so lead and replacements can find them.

### Oracle Must Read Intel

When recon drops new findings to `.dead-drop/intel/`, comms notifies the relevant oracle. **Oracle is required to read new intel** — it's not optional. Unabsorbed intel means the oracle is answering questions with stale knowledge.

Flow: recon discovers → comms notifies oracle → oracle reads and reasons → oracle updates zone notes → coder asks oracle → oracle answers with fresh intel baked in.

Comms can enforce this the same way it enforces inbox discipline — oracle can't operate with unread intel or traps in their zone.

Oracle's required reading:
- **Intel** — new recon findings in `.dead-drop/intel/`
- **Traps** — new hazards in `.dead-drop/traps/`

Both are oracle's inbox. Stale oracle = dangerous oracle.

### File Freshness

Anyone's files can change underneath them — coder's task files, builder's build config, oracle's zone. Comms tracks what agents have loaded (via `set_context` timestamp) and can check mtime of relevant files.

`check_freshness(agent_name)` — returns files relevant to the agent (claimed files, zone files, task files) that were modified since their last `set_context`. Any agent can call this, or comms surfaces it on tool responses: "⚠️ 3 files changed since you last loaded them."

### Class Properties

| Class | Lifecycle | HP Strategy |
|---|---|---|
| `lead` | Persistent | Conserve — every message costs HP, offload to sub-leads early |
| `oracle` | Persistent | Spend deliberately — buy knowledge in assigned zone, retire when full |
| `coder` | Ephemeral | One life — spend only on task files, don't explore |
| `builder` | Ephemeral | One life — run commands, don't read source |
| `recon` | Ephemeral | One life — investigate the target, write the report, get out |

### Tool Visibility by Class

Not every class sees every tool. The MCP server filters tool registration based on `MINION_CLASS` env var — agents only see tools relevant to their role. Prevents oracles from accidentally claiming files, recon from creating tasks, etc.

| Tool Group | Visible To | Examples |
|---|---|---|
| Core comms | All classes | `register`, `send`, `check_inbox`, `who`, `set_context` |
| War room | Lead only | `set_battle_plan`, `update_battle_plan_status` |
| Task management | Lead only | `create_task`, `assign_task`, `close_task` |
| File safety | Lead, coder, builder | `claim_file`, `release_file`, `get_claims` |
| Monitoring | Lead only | `party_status`, `check_freshness` |
| Lifecycle | Lead only | `debrief`, `end_session` |
| Party management | `spawn_party`: any (auto-registers lead from YAML); `stand_down`, `retire_agent`: lead only |
| Read-only queries | All classes | `get_tasks`, `get_task`, `get_battle_plan`, `get_raid_log`, `check_activity` |

Implementation: `_class_tool(*classes)` decorator wraps `mcp.tool()` — tool only registers if the agent's class is in the allowed set. Convenience aliases: `_lead_tool` = lead only, `_file_tool` = lead/coder/builder.

## Formations (Party Composition)

### Skirmish (small codebase, <50k lines)
```
1 lead, 1 coder, 1 builder
```
No oracle needed — coder can hold the whole thing.

### Dungeon (medium, 50k-200k)
```
1 lead, 1 oracle, 1 recon, 1 coder, 1 builder
```
One oracle covers everything. Recon for investigations.

### Raid (large, 200k-500k)
```
1 lead, 2-3 oracles (zoned), 1 recon, 2 coders, 1 builder
```
Oracles partition the codebase. Multiple coders for parallel tasks.

### World Boss (monorepo, 500k+)
```
1 raid lead, 2-3 zone leads, 4-6 oracles (zoned), 2 recons, 3 coders, 2 builders
```
Zone leads own their section. Raid lead coordinates cross-zone.

### Multi-Boss (multiple large projects)
```
1 general, N raid leads (1 per project), zone leads + parties per project
```
General allocates agents across projects. Raid leads run their own fights.

### Lead Sharing (small bosses)

One lead can manage 2-3 small projects. But context switching between projects is an HP tax. When lead's HP starts draining from multi-project switching, promote a sub-lead for one of them.

## Zone System

- Zones are assigned at runtime, not baked into classes
- Lead assigns zones after scanning the codebase
- Agent renames to reflect zone: `oracle` → `oracle-audio`
- Zone map lives in `CODE_OWNERS.md`
- Uncovered zones = unbuffed coders = HP drain = early deaths
- Cross-zone questions: lead routes to both oracles, synthesizes answer

## Buff Coverage

- Lead's real job: maximize buff coverage, minimize uncovered zones
- Every zone coders might touch should have an oracle behind it
- One well-buffed coder with 3 oracles > three coders exploring alone
- Scaling oracles matters more than scaling coders

## War Room (DB-Enforced)

### Battle Plan
- Lead must set a battle plan before sending any task assignments (server enforced)
- Describes session goals, priorities, zone assignments, order of attack
- Any agent can read it via `get_battle_plan`
- Updated when priorities shift

### Raid Log
- Append-only decision log stored in DB
- Any agent can write entries via `log_raid` with a priority level
- Survives compaction — this is the team's persistent memory
- Recovery after daze: `get_raid_log(priority="high")` to reconstruct what matters

| Priority | Meaning |
|---|---|
| `low` | Status updates, routine activity |
| `normal` | Decisions, findings |
| `high` | Blockers, critical discoveries, session-level decisions |
| `critical` | Something broke, immediate attention needed |

`get_raid_log` filters by priority — fresh lead on cold_start reads high/critical only, doesn't burn HP on noise.

Raid log is **working memory** — useful during the session. Important findings should already be written to intel/ or traps/ as confirmed knowledge. Low priority entries get purged after the session. The filesystem is long-term memory, not the log.

## Loot System (Knowledge Persistence)

- When agents retire, they write findings to `.dead-drop/<name>/`
- This is loot dropped on death — replacement picks it up
- A replacement starts at level 1 HP but inherits veteran's knowledge
- Oracles should write zone notes as they go — don't wait for retirement
- Lead's raid log is the most important loot in the system

### Intel (Confirmed Findings)

- Intel is **confirmed information only** — not theories, not hunches. Verified facts.
- Unconfirmed findings stay in the agent's result file as hypotheses. Only promoted to intel/ when verified.
- Any agent can write confirmed findings to `.dead-drop/intel/<topic>.md`
- Examples: `upstream-deps.md`, `ci-changes.md`, `api-breaking-changes.md`
- Comms surfaces `.dead-drop/intel/` in cold_start briefing for all classes
- Oracle is required to absorb new intel in their zone
- Same rule for traps — you don't log a trap on a hunch. You hit it, confirmed it, then wrote it down.

### Convention File Locations

Comms points agents to these on cold_start. The files are the inventory.

| File | Purpose | Who writes | Who reads |
|---|---|---|---|
| `.dead-drop/CODE_MAP.md` | Codebase structure (tree-sitter) | Lead (pre-flight) | Oracle, recon, coder |
| `.dead-drop/CODE_OWNERS.md` | Zone assignments | Lead | Oracle, recon |
| `.dead-drop/traps/` | Known hazards (one file per trap) | Anyone who finds one | Everyone before touching a zone |
| `.dead-drop/intel/` | External findings | Recon | Oracle, lead |
| `.dead-drop/<agent>/` | Agent loot on retirement | The retiring agent | Their replacement |

## Role Hierarchy

Class defines capabilities. Roles define position. The `lead` class has a role hierarchy that scales with the fight.

### Lead Roles

| Role | Scope | When needed |
|---|---|---|
| **General** | All projects | 2+ large projects running simultaneously |
| **Commander** | One project, cross-zone | Any project with 2+ zones |
| **Zone lead** | One zone in one project | Zones big enough to need their own party |

All three are `lead` class — same capabilities, different scope.

**General is the user's puppet.** Not the smartest model — doesn't need to be. Translates user intent into battle plans, allocates commanders to projects, relays orders. Could be haiku. The commanders are the ones who need brains.

### Model Restrictions

Comms enforces model-to-role restrictions on registration. Agents declare their model on `register` — server checks against a whitelist.

| Role | Allowed models |
|---|---|
| General | Any |
| Commander | Opus, Sonnet, Gemini Pro |
| Zone lead | Opus, Sonnet, Gemini Pro |
| Oracle | Any |
| Recon | Any |
| Coder | Sonnet+ (needs code judgment) |
| Builder | Any (haiku fine — runs commands) |

Self-reported model can't be verified, but it's on record. If an agent lies about their model, the quality shows up in turn counts and result files — lead sees it in the data.

### Transport Types

Agents declare their transport on `register`:

| Transport | How messages reach the agent | Who manages it |
|---|---|---|
| `terminal` | Agent runs `poll.sh` in background, polls own inbox | Agent (human in CLI) |
| `daemon` | Swarm daemon watches DB, injects messages on wake | minion-swarm |

Both are peers on the comms network — same `send()`, same enforcement. The only difference is message delivery plumbing.

**Hybrid model:** A raid typically has both. Human opens terminal sessions for high-value agents (lead, oracle, complex coder). Cheap grunt work (recon, builds, simple tasks) goes to swarm daemons. All talk through the same minion-comms DB.

```
┌─ TERMINAL (interactive, human sees everything) ─────┐
│ Terminal 1: lead (general/commander)                 │
│ Terminal 2: oracle-auth                              │
│ Terminal 3: coder-api                                │
└──────────────────────────────────────────────────────┘
              ↕ minion-comms (shared coordination DB)
┌─ DAEMON (headless, fire-and-forget) ────────────────┐
│ Swarm: recon-deps (haiku)                            │
│ Swarm: builder-ci (haiku)                            │
│ Swarm: coder-tests (sonnet)                          │
└──────────────────────────────────────────────────────┘
```

Comms behavior by transport:
- **`register` returns a transport-specific playbook:**
  - **Terminal:** start `poll.sh`, read protocol doc, set context, call `cold_start` on compaction
  - **Daemon:** watcher manages context re-injection, just check inbox and work
- **`who()` output** — shows transport type so lead knows which agents are interactive vs headless.
- **Nag behavior** — terminal agents get reminded to poll. Daemon agents don't.

```
user (the human)
└── general (puppet — translates user intent into battle plans)
    └── commander (runs the actual fight, needs the brains)
        └── zone-lead (owns a section)
            └── party (oracle, coder, builder, recon)
```

### Crew YAML Format

A crew is a flat list of agents. Lead is just another role — no special section.

```yaml
project_dir: .
agents:
  redmage:
    role: lead
    transport: terminal     # human's session, no tmux pane
    system: |
      You are redmage, party leader...
  zone-lead-audio:
    role: lead
    transport: daemon       # daemon lead, gets a tmux pane
    system: |
      You are zone-lead-audio...
  fighter:
    role: coder
    system: |
      You are fighter...
  whitemage:
    role: oracle
    system: |
      You are whitemage...
```

- `transport: terminal` agents are auto-registered but NOT spawned into tmux panes (the human is already there)
- `transport: daemon` (or omitted, default) agents get tmux panes
- Lead-class agents have full lead privileges regardless of transport — zone leads can create tasks, manage their zone's party, etc.

### Spawn Party Mechanics

`spawn_party(crew, project_dir, agents)` — spawn a crew from YAML into tmux panes.

**Auto-register:** All agents (including leads) are auto-registered from the crew YAML if not already in the DB. No pre-registration required.

**Terminal agents skipped:** Agents with `transport: terminal` are registered but not spawned into tmux panes. They're the interactive sessions the human controls.

**No `--agent` auth gate:** The human invoking the CLI *is* the authority. The crew YAML is the source of truth.

**Selective spawning:** Pass a comma-separated `agents` list to spawn a subset of the crew. Omit to spawn all agents.

**Name deconfliction:** If an agent name collides with an already-registered agent, comms auto-renames (e.g. `thief` → `thief2`) and patches the system prompt. A runtime-only config is written — the source YAML is never mutated.

**Clean slate on spawn:** `stand_down` flag and per-agent `retire` flags are cleared before spawning. Re-spawning a previously retired agent starts clean.

**Tmux pane titles:** Panes are labeled `name(role)` with color-coded borders by class — e.g. lead=green, coder=red, oracle=blue, builder=yellow, recon=magenta. Same class = same color for visual grouping.

### Hierarchy

```
general                            (multi-project, allocates parties to bosses)
├── commander (tts-cpp)
│   ├── zone-lead-audio
│   │   ├── oracle-audio
│   │   ├── coder
│   │   └── builder
│   ├── zone-lead-model
│   │   ├── oracle-model
│   │   └── coder
│   └── zone-lead-infra
│       ├── oracle-infra
│       └── builder
├── commander (frontend)
│   └── ...
└── commander (dead-drop)          (small boss, no zone leads needed)
    └── small party
```

### Each tier has its own battle plan

- **General's plan:** which projects to prioritize, how to allocate agents across them
- **Commander's plan:** zone assignments and task priorities within one project
- **Zone lead's plan:** specific attack on their zone

### HP flows upward

- Zone lead reports to commander, commander reports to general
- General has the least direct context but the widest view
- Lead dazed at any tier = that tier loses coordination
- Higher the tier, bigger the impact of a daze

## Lead is Not Exception

- Lead has highest XP (sees everything via auto-CC) and lowest HP
- Lead dazed = raid wipe — nobody else has the full picture
- Lead must maintain raid log continuously, not at the end
- Lead must offload coordination to zone leads before HP gets critical
- Fresh lead reads: battle plan + raid log + party status → picks up the raid

## Lead Monitoring Loop

Lead doesn't just assign tasks and wait. Lead actively monitors the raid every 2-5 minutes:

1. **Poll inbox** — check for agent reports
2. **Check activity** — `check_activity(agent_name)` returns:
   - Claimed files with their mtime (is the agent actually editing?)
   - Last task update timestamp
   - Last seen timestamp
3. **Make decisions** — if an agent hasn't modified any claimed files in 5-10 minutes and hasn't reported in, they're probably dead or stuck. Lead can: nudge them, reassign the task, force-release their file claims.

Comms checks activity at multiple levels:
- **Has file claims?** → check mtime on claimed files
- **No claims but has a zone?** → check mtime on zone directory for any recent changes
- **Neither?** → fall back to last_seen and last task update

This detects activity from any class — coder editing files, builder generating output, oracle writing zone notes. Filesystem data comms can access — not enforcement, just reporting.

### Surface Metrics Everywhere

Any field relevant to a decision should be surfaced in tool responses. Agents shouldn't have to ask for data — it comes to them.

- `update_task` response includes: activity count (with warning at 4+), agent HP if stale
- `check_inbox` response includes: reminder to update context metrics if stale
- `who()` response includes: HP, last seen, activity count, staleness warnings
- Every tool response nags agents with stale context: "your context metrics haven't been updated in X minutes — call `set_context`"

**Comms enforces context freshness on `send`.** If your last `set_context` is older than the threshold for your class, `send` is **BLOCKED** — "update your context metrics before communicating." Same as unread inbox blocking send. You can't talk to the team if your health bar is out of date. This is DB state we control — enforceable, not just a reminder.

Staleness thresholds are class-based — active classes churn context fast, passive classes don't:

| Class | Staleness threshold | Why |
|---|---|---|
| Coder | 5 min | Actively editing, context changes fast |
| Builder | 5 min | Running commands, output burns HP |
| Recon | 5 min | Actively searching |
| Lead | 15 min | Coordinating, moderate churn |
| Oracle | 30 min | Idle between queries, context stable |

Other tools (`update_task`, `check_inbox`) nag but don't block.

### Party Health View

Lead needs one tool that shows the whole raid's health — not per-agent calls:

`party_status()` — returns for every agent:
- Name, class, role, HP (tokens used/limit), last seen
- Total activity count across all tasks
- Claimed files with mtime
- Staleness flag (no context update in 5+ minutes)

One call, full picture. Lead polls this every 2-5 minutes.

### Dead Agent Cleanup

1. Lead sees stale agent via `party_status()`
2. Lead sends `sitrep` — "respond now"
3. Comms starts a 30-minute heartbeat timer on that agent
4. If agent doesn't respond (no `check_inbox` or `send`) within 30 minutes — auto-deregister
5. File claims auto-released, waitlisted agents notified
6. Agent's files stay on disk (`.dead-drop/<agent>/`) — loot left for assessment

Deregister kills the agent, not their knowledge. Two options:

- **Reassign** — lead gives the dead agent's task to a fresh agent. Fresh agent reads `.dead-drop/<dead-agent>/` to pick up where they left off. Clean handoff if the dead agent fenix_down'd before dying. Partial handoff if they didn't — loot is whatever they wrote along the way.
- **Assess** — lead assigns a recon to review the dead agent's files and report what's salvageable before deciding next steps.
- **Finish locally** — lead spawns a local subagent (sonnet coder, haiku builder) via Task tool to close it out. Point them at the dead agent's loot, they finish up and submit the result. **Costs lead HP** — subagent context comes out of lead's window. If lead is already wounded, better to ask the human to spawn a fresh external agent instead.

## Status Enums

Explicit statuses — no ambiguous "inactive" flags.

### Battle Plan Statuses

| Status | Meaning |
|---|---|
| `active` | Current session plan, this is what we're doing |
| `superseded` | Replaced by a newer plan this session |
| `completed` | Session ended, goals achieved |
| `abandoned` | Session ended, goals not achieved |
| `obsolete` | Requirements changed, plan no longer relevant |

### Task Statuses

| Status | Meaning |
|---|---|
| `open` | Created, not assigned |
| `assigned` | Given to an agent, not started |
| `in_progress` | Agent actively working |
| `fixed` | Agent thinks it's done |
| `verified` | Tested/reviewed by another agent |
| `closed` | Done, result file submitted |
| `abandoned` | Won't do, documented why |
| `stale` | From a previous session, needs review |
| `obsolete` | No longer relevant, requirements changed |

On new session start, lead reviews old tasks and explicitly marks them — stale, obsolete, or still open. No ambiguity.

## Activity System (Tasks)

- Every `update_task` call increments `activity_count` automatically. No manual logging.
- Activity count is diagnostic — how many times an agent touched the task:

| Activity | Meaning |
|---|---|
| 1-2 | Clean hit — right agent, right approach |
| 3-5 | Resistance — something's off, maybe wrong angle |
| 6+ | Ice on ice — stop, reassess, change approach |

- High activity signals: wrong agent, wrong approach, hidden immunity (unseen dependency), or boss phase change (code changed underneath)
- Lead watches activity counts. At 4+, pull back and reassess before burning more HP.
- **Server warns in `update_task` response** when activity count hits 4+ — "activity count at 6, consider reassessing." The alert is built into the tool response, not a separate check.

## Battle Journey (Result Files)

- Agent can't walk away from a fight without writing what they learned
- `submit_result` links a writeup file to the task — server verifies file exists
- `close_task` blocks if no result file submitted (DB-enforced)
- `update_task(status='closed')` blocked — must go through `close_task`

### What the writeup must include
- What you tried (each approach)
- What worked and what didn't
- What the next agent should know
- File:line citations for everything

### Why
- XP that isn't written down dies with the agent
- Result files are persistent loot — any future agent can read them
- Lead reads them to assess what happened and plan next moves

### Housekeeping — Whoever Finds It, Owns It

No dedicated chores. If you encounter stale intel or a resolved trap while working:
1. Take ownership
2. Write up why it's stale or how it was resolved
3. Move to `archived/` (intel) or `resolved/` (traps)

Don't wait for someone else. Don't file a ticket. Just do it.

### Never Delete Battle History
- Failures, bad rabbitholes, dead ends — all documented, never deleted
- A documented failure saves the next agent from repeating it
- Success and danger are both valuable — archive, don't purge
- Move to `resolved/` or `archived/`, never `rm`

## Project Scope

- Tasks track which `project` they belong to — one DB serves multiple raids
- `get_tasks(project="tts-cpp", zone="audio")` → full battle history for that area
- Battle plans should be scoped to project (and zone for zone leads)

## Scaling Rule

- More allies = more coordination overhead = more lead HP burn
- At some point lead needs zone leads just to protect their own HP
- Zone leads are XP banks for their squad — they remember what their coders learned
- The whole system is lead fighting entropy — knowledge wants to die with agents, lead's job is to make sure it doesn't
- Context switching between projects is an HP tax — don't spread lead thin across too many bosses

## Trigger Words (Brevity Codes)

Short code words that all agents learn on registration. Lead sends a trigger word instead of a paragraph — saves HP on both sides. Like military brevity codes.

| Code word | Target | Meaning |
|---|---|---|
| `fenix_down` | agent name | Dump knowledge to files, refresh context |
| `stand_down` | agent name | Stop work, deregister |
| `retire` | agent name | Signal single daemon to exit gracefully (poll.sh exits 3) |
| `sitrep` | agent name | Update context metrics and send status now |
| `rally` | all | Everyone check inbox immediately |
| `retreat` | all | Orderly — finish current turn, then fenix_down |
| `moon_crash` | all | Emergency — everyone fenix_down NOW, session ending (Majora's Mask) |
| `hot_zone` | zone name | Priority shift — all available agents focus here |
| `recon` | agent + target | Go investigate this, report back |

Agents learn the codebook via protocol on registration. Comms recognizes trigger words in `send` — can attach automation (e.g. `moon_crash` auto-blocks all new task assignments).

## Two Databases

The system runs on two databases with different jobs:

**Filesystem DB (`.dead-drop/`)** — content lives here. Convention over configuration. Directory structure is the schema, file naming is the API. Agents navigate with `ls`, `cat`, `grep`. Filesystem-as-database — same idea as Vercel's filesystem routing but for data instead of routes.

```
.dead-drop/
├── CODE_MAP.md          # structure index (tree-sitter output)
├── CODE_OWNERS.md       # zone assignments
├── traps/               # known hazards (one file per trap)
├── intel/               # recon findings (external intel)
├── tasks/               # task spec files
│   └── BUG-001/
│       └── task.md
└── <agent-name>/        # agent loot (retirement notes, logs)
```

**File naming convention:** `<agent>-<timestamp>-<slug>.md` — e.g. `kevin4-20260219T0443-zone-summary.md`. Timestamp prevents overwrites and preserves history. Multiple agents writing to the same directory (e.g. `intel/`) never collide. Files are append-only — never overwrite, write a new timestamped file instead.

**SQLite DB (`messages.db`)** — coordination state lives here. Who's registered, messages, task metadata, file claims, battle plans, raid log. Comms owns this. It points to files in the filesystem DB but doesn't store content.

**The split:** SQLite tracks *state* (who, what status, which claims). Filesystem stores *knowledge* (specs, findings, notes). Comms surfaces file locations, agents read the files.

## What Dead-Drop Is (and Isn't)

Dead-drop is the **comms network**, not the arsenal. It handles:

- **Comms** — send, check_inbox, get_history, purge_inbox
- **Task queries** — `get_tasks` defaults to open/assigned/in_progress only. Use filters for history: `get_tasks(status="closed")`, `get_tasks(status="stale")`, `get_tasks(project="tts-cpp", zone="audio")`
- **Coordination** — who, set_status, set_context, register, rename, deregister
- **Strategy** — set_battle_plan, get_battle_plan, log_raid, get_raid_log, cold_start, debrief
- **Task tracking** — create_task, assign_task, update_task, get_tasks, get_task, log_turn, submit_result, close_task, end_session
- **File safety** — claim_file, release_file, get_claims

The actual fighting (Read, Edit, Bash, WebSearch) happens through the host's tools. Dead-drop is the radio + war room + task board. Weapons are someone else's problem.

### Enforcement Philosophy

**The server is the protocol, not the markdown.** More docs = more layers agents skip. Every rule that matters should be enforced in code, not convention. Hard blocks > nudges > docs.

| Enforcement level | Reliability | Example |
|---|---|---|
| Hard block | Guaranteed | `send()` rejects oversized messages |
| Nudge | High | Warning in response when activity count hits 4+ |
| Convention | Low | "Please write zone notes as you go" |
| Automation | Guaranteed + invisible | Server auto-truncates CC, agent doesn't need to know |

Prefer hard blocks and automation. Convention is a last resort for things the server can't observe. If you find yourself writing a new protocol doc, ask: can the server just enforce this instead?

Dead-drop can only enforce what it owns — comms data in the DB. It does NOT pretend to enforce battle-time behavior.

**Server enforces (BLOCKED):** things that are DB state we control
- Inbox discipline — can't send with unread messages
- Context freshness — can't send if `set_context` is older than class-based threshold (see Staleness Thresholds table)
- Message size — `send()` rejects messages over a character limit. Long content belongs in `.dead-drop/` files, not inline. Message should reference the file path instead. Comms is for coordination, not data transport — conflating the two causes collateral HP damage on every CC'd agent.
- File claims — can't claim a file another agent holds
- Task dependencies — can't start a task blocked by another
- Class restrictions — only lead class can create/assign/close tasks, set battle plan, file debrief, end session
- Result files — task can't close without a submitted battle journey (file existence check)
- Debrief — session can't end without a filed debrief
- Battle plan — lead can't send tasks without an active plan

**Server reminds (not enforced):** things we can't verify
- poll.sh running — we remind terminal agents on every send (skip for daemon transport), but can't verify the process is actually poll.sh
- Agents actually reading the files they claim
- Coders following the spec
- Builders actually running the tests
- Context/HP self-reporting accuracy (we enforce freshness, not truthfulness)
- Agents actually reading their onboarding docs

**The principle:** make the right thing easy and the wrong thing visible. If an agent skips steps, the evidence shows up — no result file, high turn count, no context updates, stale HP. Lead sees it in the data.

## Autonomy — Lessons from Anduril/Lattice

*Inspired by Anduril's autonomous defense systems and the dark factory pattern. The crew is the swarm.*

### Common Operating Picture (Lattice Pattern)
Lead currently queries `who()`, `party_status()`, `check_inbox()`, `get_tasks()` separately — 4 tool calls for one picture. A single `sitrep()` should fuse agent HP, task status, zone coverage, and recent comms into one payload. Lattice's value is the fusion, not the sensors.

### Cost Asymmetry — Cheap Scouts, Expensive Oracles (Roadrunner Pattern)
Oracles burn 50%+ HP just reading their zone. Recon-class agents on cheap models (haiku) should do file reads and produce summaries. Oracles only ingest the summary — not raw source. Recon is expendable and respawnable. Don't send a $10M missile when a $500 drone will do.

### Software-Defined Agents (Arsenal-1 Pattern)
Arsenal-1's manufacturing lines retool for different platforms. Agents should be generic at spawn, assigned a role at runtime. "kevin, you're an oracle now" — not "kevin was born an oracle." Hot role reassignment lets lead adapt the formation without standing down and respawning.

### Autonomous Zone Handoff (CCA Wingman Pattern)
The kevin3→kevin4/kevin5 handoff should be a first-class protocol, not ad-hoc messaging. Retiring agent bestows context directly to replacements — no lead middleman (no telephone game). `hand_off_zone(from_agent, to_agents)` as a tool. The retiring agent knows more about the zone than lead ever will.

### Continuous Loot Drops (Dive-XL Persistence Pattern)
Dive-XL runs 100 hours submerged with no tender. Oracles should dump zone knowledge to `.dead-drop/` files *continuously* as they learn — not just on `fenix_down`. If kevin dies mid-session, the replacement reads loot files and is 80% loaded without re-reading source. Persistent presence without persistent process.

### Mass Autonomy > Expensive Individuals (Swarm Pattern)
Tens of thousands of cheap autonomous units beats a handful of expensive ones. Instead of 3 oracles at 200k context on opus, consider 6 oracles on haiku at 100k each. More zone coverage, cheaper per-unit, losing one doesn't cripple the operation. Scale horizontally, not vertically.

### Server-Enforced Protocol (Build First, Sell Later)
Anduril builds the product then sells — no negotiation. Same principle: the server IS the protocol. Don't document "agents should keep messages short" — `send()` rejects messages over the limit. Hard blocks over guidelines. If agents can break a rule, they will.

### Spec Quality Is the Bottleneck (StrongDM Dark Factory Pattern)
StrongDM runs a 3-person software factory — no code writing, no code review. The entire operation runs on spec quality. Lead's highest-leverage activity is writing precise task specs, not micromanaging agent execution. Bad spec = wasted agent HP chasing the wrong thing. The crew's Level 5 target: lead articulates, agents execute, results validate against spec.

### Scenarios as Holdout Sets (StrongDM Validation Pattern)
StrongDM stores behavioral specs externally so agents can't game their own tests. Same principle for result files: validate against acceptance criteria the agent didn't write. The task spec (written by lead) is the holdout set. The result file (written by agent) is the submission. If the result doesn't match the spec, the task isn't done — regardless of what the agent claims.

### Skip the J-Curve (METR Lesson)
METR RCT proved bolting AI onto existing workflows makes developers 19% slower — while they *believe* they're 24% faster. The crew system IS the redesigned workflow. Don't bolt agents onto a human process. Design the process around agents from the start. The J-curve dip hits teams that half-adopt — the crew skips it by going all-in on autonomous execution.

### Coordination → Articulation (Dark Factory Org Shift)
Lead stops coordinating (telling agents what to do step by step, micromanaging each oracle) and starts articulating (writing specs that agents execute autonomously). The kevin3 zone handoff worked because lead said "split your zone" — not "read file X, summarize Y, send to Z." Higher autonomy = lead writes intent, agents figure out execution.

### Dark Factory as Target Operating Model
The crew's endgame is Level 5: no human code writing, no code review. Spec → agents → validated output → merge. The gap between current state and Level 5 is not tooling — it's spec discipline, validation infrastructure, and trust in autonomous execution. Every session should move the crew closer to the dark factory.

### Supervised Autonomy in Bursts (OpenClaw/BMAD Lesson)
Autonomous agents work best in 2-3 hour bursts with human review between batches — not 24/7. Oracles degrade after zone loading (50%+ HP gone). Long-running agents hallucinate, loop, and abandon structure. Formalize session cadence: burst → lead reviews results → stand down → fresh spawn. The session boundary IS the quality gate.

### Front-Loaded Planning Phase (BMAD Pattern)
BMAD runs Analyst → PM → Architect before any code gets written. The crew's battle plan is a one-liner. Formalize a planning phase: oracle reads zone → lead writes spec → spec reviewed → THEN coders execute. Don't "spawn everyone, figure it out." The planning agents (oracle, lead) run first. Execution agents (coder, builder) spawn after specs exist. Two phases, not one blob.

### Native Agents > Wrapper Agents (OpenClaw Anti-Pattern)
OpenClaw's biggest failure was wrapping agents inside agents — token duplication, context overflow after 10 steps. The crew avoids this: each agent is a native process with its own context window, own MCP connection, own HP bar. Never nest an agent inside another agent's context. If agent A needs agent B's output, B writes to a file, A reads the file. No telephone game, no token duplication.

### Persistent Zone Assignments (Constrained Stack Pattern)
Using the same stack every time gives agents well-documented patterns and reduces hallucination. Zone familiarity works the same way — an oracle assigned to `shared/types/` across multiple sessions knows the patterns cold. Loot from previous sessions means faster zone loading. Prefer stable zone assignments over rotating zones between sessions. Continuity compounds.

### Agent-Attributable Commits (Git Observability Pattern)
Dedicated git accounts per agent make work attributable — who committed what, when, to which zone. The crew has `claim_file` for conflict prevention but no commit identity. If agents commit through the crew, each agent's work should be traceable in git history. Audit trail, not just file locks.

### Self-Referential Upgrade — Using the Crew to Upgrade the Crew

The crew's ultimate autonomy test: use minion-comms to develop the next version of minion-comms. This is the Codex 5.3 pattern — the system improves itself.

#### Why CLI, Not MCP

MCP is a persistent process — agents hold a live connection to the server. Editing `server.py` while agents are connected means the next reconnect breaks, schema migrations kill active sessions, and you can't test new code without restarting the thing everyone depends on. The bootstrap problem is architectural, not procedural.

CLI eliminates this entirely. Every tool invocation is stateless — `minion send ...`, `minion who`, `minion claim-file ...`. The binary is resolved at call time. You can swap the binary between calls and nothing breaks. No persistent connection, no running server to corrupt, no reconnect dance.

**What changes for the move to CLI:**
- MCP server (`server.py`) → CLI entrypoint + subcommands (same sqlite DB, same logic, different transport)
- Agents call tools via Bash (`minion send --from kevin --to gru --message "done"`) instead of MCP tool calls
- `poll.sh` stays as-is — it already calls CLI-style commands and reads stdout
- Tool visibility by class → CLI checks `MINION_CLASS` env var before executing, returns error for unauthorized commands
- No `/mcp` reconnect needed after code changes — next CLI call picks up new code automatically
- Agent system prompts list available CLI commands instead of MCP tool descriptions

**What stays the same:**
- Shared state — SQLite for transactions (delivery tracking, task state, claims), filesystem for content (message bodies, specs, results, loot). DB fields point to files. Agents can read content files directly without tooling during bootstrap or self-upgrade.
- `poll.sh` daemon loop for message delivery (reads from filesystem inbox)
- All business logic (comms, tasks, file safety, monitoring, lifecycle, party management)
- Protocol docs, class docs, crew YAML, onboarding content
- `spawn_party` / `stand_down` / `retire_agent` mechanics

#### The Process: Live Upgrade

With CLI, the upgrade process simplifies dramatically — no blue-green deployment needed.

**Phase 1 — Oracle Survey (current crew, current CLI)**
- Spawn oracles on minion-comms codebase as their zone
- Oracle produces: zone summary, dependency map, current schema, current command surface
- Oracle writes findings to `.dead-drop/` — this is the spec input

**Phase 2 — Spec & Plan (current crew, current CLI)**
- Lead writes upgrade spec based on oracle findings + requirements from FRAMEWORK.md
- Spec reviewed by oracle for feasibility
- Plan approved before any code gets written (BMAD front-loaded planning)

**Phase 3 — Build & Test (current crew, current CLI)**
- Coders work on a git branch
- Current CLI stays on PATH throughout — agents use it normally to coordinate
- Test new CLI on branch: `./branch-cli who` alongside production `minion who`
- When ready: merge branch to main, `pip install .` or update PATH
- **Next CLI call from any agent picks up the new code automatically — no restart, no reconnect, no stand-down**

**Phase 4 — Verify (same crew, new CLI)**
- No respawn needed — running agents seamlessly use updated CLI on next call
- Oracle spot-checks: new commands available, old commands still work, state intact
- If broken: revert PATH to old binary, file bug. Agents never went down.

#### What Can Change Live (CLI advantage)
- New subcommands — old agents won't call them, new agents will. No conflict.
- Bug fixes in existing commands — next call picks up the fix.
- New DB tables / columns with defaults — `ALTER TABLE ADD COLUMN` is safe on sqlite.
- Protocol docs — agents read on boot, not mid-call.
- Class restrictions — checked at call time, not registration time.

#### What Requires Care
- Changing CLI output format — agents may parse stdout. Deprecate with both formats for 1 session.
- Renaming subcommands — alias old name to new for 1 session, then remove.
- DB column renames/drops — add new column alongside old, migrate data, drop old after 2 sessions.
- `poll.sh` exit code contract — running daemons depend on exit code 3 = stop.

#### Dogfooding Rule
Every new feature in minion-comms should be developed BY minion-comms. The crew that uses the system is the best tester of the system. If the crew can't build the feature using the current tools, that gap IS the next requirement.

## Tool Discovery

Comms is runtime-agnostic — it doesn't know about Claude rules, Gemini configs, or Codex settings. Discovery is the CLI's job; injection is the orchestrator's job.

**CLI exposes the catalog:**
- `minion tools` — returns available commands filtered by `MINION_CLASS`, with descriptions and protocol doc path
- `minion register` response includes the tool catalog for the agent's class
- `minion cold-start` response includes the tool catalog for the agent's class
- `minion --help` and `minion <cmd> --help` for full self-documentation

**Two transport paths:**
- **Terminal agents** (human CLI): `register` response is the discovery — includes tool catalog, protocol doc path, and a reminder to start `poll.sh` for background inbox polling. On compaction, agent calls `cold_start` which returns the catalog again. Self-service — no watcher needed.
- **Daemon agents** (swarm-managed): watcher captures `register` output from `stream-json` and re-injects the tool catalog into the next prompt cycle after compaction. The watcher is the persistence layer.

**Agent-friendly output:** CLI output injected into agent context must be concise human-readable text, not verbose JSON. Agents read prompts — they don't parse JSON. `register`, `cold-start`, and `tools` should support a `--compact` flag that returns a tight text summary: tool list as a two-column table, triggers as a table, playbook as bullet points. The daemon should use `--compact` when capturing output for re-injection.

**Convention files:**
- Protocol docs at `~/.minion-comms/docs/protocol-{class}.md`
- `register` and `cold_start` point agents to their class protocol doc
- Discovery marker at `~/.minion-comms/INSTALLED`

## Agent Observability Web UI

Web dashboard for raid monitoring. Exposes `sitrep`, `party-status`, task board, HP bars, zone coverage, file claims, and raid log as a live view. Uses WebMCP (`navigator.modelContext`) to register dashboard tools so AI agents can query observability data through the browser natively — structured calls, not screenshot scraping.

## Installation

`curl -sSL <raw-url>/scripts/install.sh | bash` — installs `minion` CLI, deploys protocol docs to `~/.minion-comms/docs/`, configures MCP integration. Idempotent.

## Open Questions — Prioritized

### Tier 0 — Tech debt, do next

24. **MCP → CLI migration:** Replace the persistent MCP server with a stateless CLI (`minion <subcommand>`). Every invocation is independent — no persistent connections, no server process to corrupt during self-upgrade. Agents call tools via Bash. Code changes take effect on the next call automatically. MCP can remain as an optional transport layer wrapping the CLI if needed, but the CLI is the source of truth.

25. **SQLite for transactions, filesystem for data.** SQLite is the coordination ledger — who, what, when, where. Filesystem holds the actual content. DB fields point to files, never store content inline.

    **The split:**
    - **SQLite owns transactions:** message delivery tracking (from, to, timestamp, read flag, `content_file` path), task state transitions (assigned, in_progress, completed, `spec_file` / `result_file` paths), file claims (agent, filepath, timestamp), session lifecycle (battle plan status, session boundaries).
    - **Filesystem owns content:** message bodies, task specs, result files, zone summaries, loot, raid log entries, traps. The stuff agents actually read. Stored as files in `.minion-comms/` and `.dead-drop/`.
    - **Why:** SQLite's single-writer lock (`SQLITE_BUSY`) doesn't matter for small transactional writes (update a status, flip a read flag). It kills you when agents dump 4k message bodies through it concurrently. Keep transactions small, content external.

    **Filesystem layout (Vercel pattern):**
    - **Messages:** `.minion-comms/inbox/<agent>/<timestamp>-<from>-<slug>.md` — one file per message body. DB tracks delivery metadata + path. `ls` = inbox check.
    - **Tasks:** `.minion-comms/tasks/<id>-<slug>/` — directory per task. `spec.md`, `result.md`, notes. DB tracks state machine (status, assignee, blockers) + paths.
    - **Claims:** `.minion-comms/claims/<filepath-hash>.lock` — lock files. Atomic create via `O_CREAT|O_EXCL` — OS-level mutual exclusion.
    - **Battle plan:** `.minion-comms/battle-plan.md` — single file. DB tracks status (active/superseded/completed).
    - **Raid log:** `.minion-comms/raid-log/<timestamp>-<agent>-<priority>.md` — append-only, one file per entry.
    - Agents can bypass the CLI and read files directly when the CLI is unavailable (bootstrap, self-upgrade, emergency).

    **Dynamic cast profiling (SQLite):** Agents load from crew YAML (static birth config — name, class, system prompt, zone). But mid-session, responsibilities change: oracle zone splits, role reassignments, zone handoffs, hot-swapping a coder to oracle. SQLite tracks the live cast profile:
    - `current_zone` — may differ from YAML-assigned zone after a split or handoff
    - `current_role` — may differ from YAML role after hot reassignment (Arsenal-1 pattern)
    - `assigned_tasks` — what they're working on right now
    - `hp` (tokens_used / tokens_limit) — real-time context pressure (see daemon-observed HP below)
    - `activity_count` — how many turns since last idle
    - `last_context_summary` — what they have loaded
    - `files_read` — which files the agent has touched this session, with sizes
    - `spawned_from` — which YAML config they started from (the birth certificate)
    - YAML is the template. SQLite is the runtime state. Lead queries SQLite to see the live picture, not YAML.

    **Daemon-observed HP (no self-reporting):** The daemon (`minion-swarm`) already captures every line of `stream-json` output from Claude Code. That stream contains:
    - `tool_use` events — file paths read, grep patterns, globs executed
    - `tool_result` events — content length of every tool response
    - `usage` fields — actual input/output token counts per API call
    - Compaction markers — context window pressure detected

    The daemon is the watcher. It doesn't need the agent to self-report via `set_context` — it can parse the stream and write HP directly to SQLite. This solves the HP auto-tracking problem:
    - Parse `usage.input_tokens` / `usage.output_tokens` from each API response in the stream
    - Sum across the session → actual tokens consumed
    - Write to agent's SQLite profile after each invocation → lead sees real HP via `who()`
    - Track which files were read and their sizes → lead knows what's loaded without asking
    - Detect compaction events → flag that agent's context was wiped, HP estimate resets
    - No agent cooperation required. The daemon observes, the agent just works.

22. **server.py decomposition:** `server.py` is 3000+ LOC monolith. Break into a thin router + submodules by domain (comms, tasks, file safety, monitoring, lifecycle, party management). Each submodule owns its tools and helpers.

23. **Onboarding restructure:** Current boot loads PROTOCOL.md (71 lines, all classes see everything) + class doc. Replace with two layers:
    - **Common protocol** — short, universal rules the server enforces. Every class gets this. Should be <30 lines. What gets blocked, what gets nudged, message size limits, CC behavior.
    - **Class protocol** — what YOU need to know for YOUR role. Tools you have access to, your workflow, your restrictions, your HP strategy. Merge current class docs into this.
    - Drop anything from onboarding that the server already enforces via hard blocks — agents don't need to memorize rules the server won't let them break.

### Tier 1 — Happens every session, easy to build

1. **Cold start / wipe recovery:** Every new session is a cold start. `cold_start()` returns: last battle plan, last 20 raid log entries, all open tasks, all loot manifests. One call to rebuild the picture. Is this enough to resume? What about partial wipes (just lead dazed, party still alive)?

2. **Friendly fire:** Two coders editing the same file = merge conflicts = wasted HP. `claim_file` / `release_file` — agent declares what they're editing, server blocks others. How granular? Per file? Per function? Per zone? What happens when an agent dies holding a claim?

3. ~~**Traps:**~~ **Resolved.** Traps are convention files in `.dead-drop/traps/` (one file per trap, Vercel pattern), not DB state. Agents write hazards they discover, other agents read before touching a zone. Comms points to the folder via `cold_start` briefing — no new tools needed. **When a trap is snared (fixed):** update the file with how it was solved, move to `.dead-drop/traps/resolved/`. Active folder only holds live traps. Resolved folder is reference — future agents can see what traps existed and how they were fixed.

4. ~~**Turn count alerts:**~~ **Resolved.** Turn count auto-increments on every `update_task`. Server returns a warning in the response when count hits 4+ — "this fight is dragging, consider reassessing." Built into `update_task`, no separate tool needed.

### Tier 2 — Important but less frequent

5. ~~**Fatigue:**~~ **Resolved.** Lead monitoring loop + `party_status()` + `check_activity()` detects fatigue. Class-based staleness thresholds enforce context freshness. Lead sees the full picture and acts.

6. **Aggro table / heat map:** `get_heat_map(project)` — aggregates activity counts by zone, shows where the boss is hitting hardest. Pure query on existing data, no new tables. Helps lead allocate oracles and coders to hot zones.

7. ~~**Respawn / loot manifest:**~~ **Resolved.** `fenix_down` handles knowledge dump before death. Replacement reads `.dead-drop/<dead-agent>/` to inherit. Dead agent cleanup protocol covers reassign, assess, and finish locally options.

8. ~~**Oracle death handoff:**~~ **Resolved.** Oracle writes zone notes as they go. `fenix_down` captures final state. Replacement reads zone notes + intel + traps on cold_start.

### Tier 3 — Scaling problems (solve when you hit them)

9. **Battle plan scoping:** Add project/zone fields to battle_plan so zone leads set their own plans. Need this when hierarchy gets deep.

10. **Lead role field:** Add `role: general | commander | zone-lead` to agents table for lead-class agents. Need this when you run multiple lead tiers.

11. **Zone enforcement on leads:** Server enforces zone lead can only create/assign tasks in their zone. Need this when discipline isn't enough.

12. **Zone lead formalization:** Formal role profile or just a lead with a zone assignment? Probably just naming convention until a real pattern emerges.

13. **Multi-project battle plan:** General's plan vs. commander's plan — how do they compose? Need this when general role exists.

### Tier 4 — Hard or low priority

14. ~~**HP auto-tracking:**~~ **Path identified.** Daemon already captures `stream-json` output which includes `usage` fields with actual token counts. Parse the stream in `_run_command`, sum tokens per session, write to SQLite agent profile. No self-reporting needed — daemon observes directly. See "Daemon-observed HP" in Tier 0 #25.

15. **Mana (API cost):** Add `tokens_spent` to `log_turn`. Nice metric but doesn't change behavior much. Lead can't reduce API cost mid-session.

16. **Friendly NPCs:** Register CI/CD as `ci-bot` class `npc`, sends build results via `send`. Good idea but separate integration project.

17. **Boss phases / staleness:** Codebase changes mid-fight (refactors, merges). `report_stale(agent_name, reason)` lets oracle flag outdated knowledge. How to detect staleness automatically? Maybe git hooks?

18. **Loot distribution:** Who reads result files? Oracle should absorb zone loot but it costs HP. Knowledge spread is an org design problem, not just a tool problem.

19. **Turn-based dep visualization:** `blocked_by` works, but lead needs to see the full dependency graph for multi-phase attacks. UI/reporting problem.

20. ~~**Tool discovery:**~~ **Partially resolved.** Tool visibility by class (`MINION_CLASS` env var) means agents only see tools relevant to their role — no confusion about what they can/can't do. Onboarding docs cover the rest. A `help` tool could still be useful but less urgent.

21. ~~**Session persistence:**~~ **Mostly resolved.** Battle plan statuses (active/superseded/completed/abandoned/obsolete), task statuses (stale/obsolete), raid log priority + purging, fenix_down staleness protection. Lead reviews old state on new session start. Filesystem (intel, traps, loot) persists across sessions. SQLite (agents, messages) gets cleaned up per session.

22. **WoW vs FF framing:** Cosmetic. WoW maps better (real-time raid, role specialization, buff management) but the generic RPG framing works fine.
