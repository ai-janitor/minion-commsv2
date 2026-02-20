# Minion Comms — Common Protocol

## Hard Blocks (Server-Enforced)

These will BLOCK your commands. Don't fight them — comply.

1. **Inbox discipline:** `send` blocked if you have unread messages. Call `minion check-inbox` first.
2. **Context freshness:** `send` blocked if your `set-context` is stale. Thresholds: coder/builder/recon 5m, lead 15m, oracle 30m.
3. **Battle plan required:** No `send` or `create-task` without an active battle plan.
4. **File claims:** Can't claim a file another agent holds. You're auto-waitlisted.
5. **Task close requires result:** `close-task` blocked without a submitted result file.
6. **Class restrictions:** Lead-only commands reject non-lead callers.

## Auto Behaviors

- **Auto-CC lead:** Every non-lead message is CC'd to lead automatically.
- **Trigger detection:** Trigger words in messages are auto-detected and flagged.
- **Activity warnings:** `update-task` warns at activity count 4+.

## CLI Usage

All commands: `minion <command> [options]`. JSON output by default, `--human` for tables.

```bash
minion register --name <name> --class <class>
minion check-inbox --agent <name>
minion send --from <name> --to <target> --message "..."
minion set-context --agent <name> --context "what you have loaded"
minion who
minion sitrep                    # fused view of everything
```

## Trigger Words

Use in messages for fast coordination. Server detects automatically.

| Code | Effect |
|------|--------|
| `fenix_down` | Dump knowledge to disk |
| `moon_crash` | Emergency — blocks all task assignments |
| `stand_down` | All daemons exit gracefully |
| `sitrep` | Request status report |
| `rally` | Focus on target |
| `retreat` | Pull back, reassess |

## Filesystem Locations

- Messages: `~/.minion_work/<project>/inbox/<agent>/`
- Battle plans: `~/.minion_work/<project>/battle-plans/`
- Raid log: `~/.minion_work/<project>/raid-log/`
- Protocol docs: `~/.minion_work/docs/`
- Loot: `.dead-drop/<agent>/`
- Intel: `.dead-drop/intel/`
- Traps: `.dead-drop/traps/`
