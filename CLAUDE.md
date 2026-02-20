# minion-commsv2

CLI-first multi-agent coordination framework. RPG raid party metaphor over SQLite.

## Agent Bootstrap

Read `AGENTS.md` for the universal agent playbook (boot sequence, classes, HP, hard blocks, crew lifecycle). Everything there applies regardless of runtime.

## Dev Reference

| What | Where |
|------|-------|
| CLI entry point | `src/minion_comms/cli.py` |
| Auth model (class → commands) | `src/minion_comms/auth.py` |
| DB schema (all tables) | `src/minion_comms/db.py` |
| Comms (send, check-inbox, set-context) | `src/minion_comms/comms.py` |
| Crew lifecycle (spawn, stand-down, retire) | `src/minion_comms/crew.py` |
| HP + monitoring | `src/minion_comms/monitoring.py` |
| Task management | `src/minion_comms/tasks.py` |
| File claims | `src/minion_comms/filesafety.py` |
| War room (battle plans, raid log) | `src/minion_comms/warroom.py` |
| Trigger words | `src/minion_comms/triggers.py` |
| Agent lifecycle (cold-start, fenix-down) | `src/minion_comms/lifecycle.py` |
| Full framework spec | `FRAMEWORK.md` |
| Agent protocol docs | `docs/protocol-{class}.md` |
| Daemon polling | `src/minion_comms/polling.py` |
| Tests | `tests/test_*.py` (mirror source modules) |

## CLI Gotchas

- **`--human`/`--compact` are global flags** — go BEFORE the command, not after
- **`MINION_CLASS` env var** gates auth per `auth.py`
- All commands are stateless — no persistent server connection

## Running Tests

```bash
uv run pytest
```
