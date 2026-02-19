# AGENTS.md — Universal Agent Bootstrap

This file is for any AI agent (Claude, Gemini, Codex, etc.) operating as a minion.
Read this FIRST, then your class protocol at `docs/protocol-{class}.md`.

## What This Is

A CLI-first multi-agent coordination framework. You coordinate with other agents through `minion <command>`. All state lives in SQLite. All output is JSON (or `--human` for tables, `--compact` for context injection).

## Boot Sequence

```bash
# 1. Register yourself
minion register --name <your-name> --class <your-class> --transport terminal

# 2. Read your class protocol (returned in register response, also at):
#    docs/protocol-{class}.md

# 3. Get situational awareness
minion cold-start --agent <your-name>

# 4. Report your context (REQUIRED before you can send messages)
minion set-context --agent <your-name> --context "what I have loaded" \
  --tokens-used <N> --tokens-limit <M>

# 5. Check inbox
minion check-inbox --agent <your-name>
```

## Classes

| Class | You Are | You Can | You Cannot |
|-------|---------|---------|------------|
| lead | Commander | Create/assign/close tasks, manage crews, battle plans | Edit source code |
| coder | DPS | Claim files, edit code, submit results | Create tasks, manage crews |
| builder | Tank | Run builds/tests, claim files | Edit source, create tasks |
| oracle | Sage | Hold zone knowledge, answer questions | Edit source, create tasks |
| recon | Scout | Investigate external problems | Edit source, create tasks |

Full auth matrix: `src/minion_comms/auth.py`

## CLI Basics

**Global flags go BEFORE the command:**
```bash
minion --human who        # correct
minion who --human        # WRONG
```

**Essential commands (all classes):**
```bash
minion who                           # list agents
minion sitrep                        # full situation report
minion check-inbox --agent <name>    # read messages (MUST do before send)
minion send --from <name> --to <target> --message "..."
minion set-context --agent <name> --context "..." --tokens-used N --tokens-limit M
minion get-tasks --agent <name>      # list tasks
minion get-task --task-id N          # task detail
minion tools [--class <class>]       # what commands you have
```

**Full command list:** `minion --help`
**Per-command help:** `minion <command> --help`

## Hard Blocks (Server Will Reject You)

1. **Unread inbox** → `send` blocked. Call `check-inbox` first.
2. **Stale context** → `send` blocked. Call `set-context` (thresholds: coder/builder/recon 5m, lead 15m, oracle 30m).
3. **No battle plan** → `send` and `create-task` blocked.
4. **File already claimed** → `claim-file` blocked. You're auto-waitlisted.
5. **No result file** → `close-task` blocked.
6. **Wrong class** → Lead-only commands reject non-lead callers.

## HP (Context Window Health)

Your context window is your health bar, **reversed**:
- Empty context = 100% HP (fresh)
- Full context = 0% HP (dead)

| Remaining | Status | What Happens |
|-----------|--------|-------------|
| >50% | Healthy | Work normally |
| 25-50% | Wounded | Light tasks only |
| <25% | Critical | Retire, spawn replacement |

Report HP via `set-context`. Lead monitors via `party-status`.

## Crew Lifecycle

```bash
# Lead spawns a crew
minion spawn-party --agent <lead> --crew <crew.yaml>

# Lead dismisses the crew
minion stand-down --agent <lead> --crew <crew-name>
# Without --crew: kills ALL crews

# Lead retires one agent
minion retire-agent --agent <target> --requesting-agent <lead>
```

## Knowledge Persistence (Phoenix Down)

Before your context dies, dump what you learned:
```bash
minion fenix-down --agent <name> --files "file1.md,file2.md" --manifest "what I learned"
```
Next agent's `cold-start` picks up unconsumed fenix records.

## Source Map

Read these when you need to understand internals:

| What | File |
|------|------|
| CLI commands + args | `src/minion_comms/cli.py` |
| Auth (class → allowed commands) | `src/minion_comms/auth.py` |
| DB schema (all tables) | `src/minion_comms/db.py` |
| Comms (send, inbox, context) | `src/minion_comms/comms.py` |
| Crew (spawn, stand-down, retire) | `src/minion_comms/crew.py` |
| Tasks (create, assign, close) | `src/minion_comms/tasks.py` |
| Monitoring (HP, party-status) | `src/minion_comms/monitoring.py` |
| Lifecycle (cold-start, fenix-down) | `src/minion_comms/lifecycle.py` |
| File claims | `src/minion_comms/filesafety.py` |
| War room (battle plans, raid log) | `src/minion_comms/warroom.py` |
| Trigger words | `src/minion_comms/triggers.py` |
| Full framework spec | `FRAMEWORK.md` |
| Daemon polling contract | `scripts/poll.sh` |
