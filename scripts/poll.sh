#!/usr/bin/env bash
# poll.sh — inbox poller for terminal-transport agents.
#
# Usage: poll.sh <agent-name> [--interval <seconds>] [--timeout <seconds>]
#
# Exit codes (same contract as v1 — minion-swarm depends on these):
#   0 — message(s) received and printed
#   1 — timeout reached with no messages
#   2 — error (agent not registered, DB unreachable, etc.)
#   3 — stand_down or retire flag detected, agent should exit

set -euo pipefail

AGENT="${1:?Usage: poll.sh <agent-name> [--interval N] [--timeout N]}"
shift

INTERVAL=5
TIMEOUT=0  # 0 = poll forever

while [[ $# -gt 0 ]]; do
    case "$1" in
        --interval) INTERVAL="${2:?--interval requires a value}"; shift 2 ;;
        --timeout)  TIMEOUT="${2:?--timeout requires a value}"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

ELAPSED=0

while true; do
    # Check stand_down flag
    STAND_DOWN=$(minion sitrep 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    flags = d.get('flags', {})
    sd = flags.get('stand_down', {})
    print(sd.get('value', '0'))
except:
    print('0')
" 2>/dev/null || echo "0")

    if [[ "$STAND_DOWN" == "1" ]]; then
        echo "[poll.sh] stand_down flag detected for $AGENT. Exiting." >&2
        exit 3
    fi

    # Check per-agent retire flag
    RETIRE=$(python3 -c "
import sqlite3, os
db = os.environ.get('MINION_COMMS_DB_PATH', os.path.expanduser('~/.minion-comms/minion.db'))
try:
    conn = sqlite3.connect(db, timeout=1)
    cur = conn.execute('SELECT agent_name FROM agent_retire WHERE agent_name = ?', ('$AGENT',))
    print('1' if cur.fetchone() else '0')
    conn.close()
except:
    print('0')
" 2>/dev/null || echo "0")

    if [[ "$RETIRE" == "1" ]]; then
        echo "[poll.sh] retire flag detected for $AGENT. Exiting." >&2
        exit 3
    fi

    # Check inbox
    RESULT=$(minion check-inbox --agent "$AGENT" 2>/dev/null || echo '{"messages":[]}')

    MSG_COUNT=$(echo "$RESULT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    msgs = d.get('messages', [])
    print(len(msgs))
except:
    print(0)
" 2>/dev/null || echo "0")

    if [[ "$MSG_COUNT" -gt 0 ]]; then
        echo "$RESULT"
        exit 0
    fi

    sleep "$INTERVAL"
    ELAPSED=$((ELAPSED + INTERVAL))

    if [[ "$TIMEOUT" -gt 0 && "$ELAPSED" -ge "$TIMEOUT" ]]; then
        exit 1
    fi
done
