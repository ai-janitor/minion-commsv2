#!/usr/bin/env bash
# poll.sh — inbox poller for daemon-transport agents.
#
# Usage: poll.sh <agent-name> [--interval <seconds>] [--timeout <seconds>]
#
# Exit codes (same contract as v1 — minion-swarm depends on these):
#   0 — message(s) waiting (NOT consumed — agent must call check-inbox)
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

DB="${MINION_COMMS_DB_PATH:-$(python3 -c "import os; print(os.path.expanduser('~/.minion-comms/minion.db'))")}"

ELAPSED=0

while true; do
    # All checks in one DB query: unread count + stand_down + retire
    RESULT=$(python3 -c "
import sqlite3, os, json, sys

db = '$DB'
agent = '$AGENT'

try:
    conn = sqlite3.connect(db, timeout=2)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Unread direct messages
    cur.execute('SELECT COUNT(*) FROM messages WHERE to_agent = ? AND read_flag = 0', (agent,))
    direct = cur.fetchone()[0]

    # Unread broadcasts
    cur.execute('''SELECT COUNT(*) FROM messages
        WHERE to_agent = \"all\" AND from_agent != ?
        AND id NOT IN (SELECT message_id FROM broadcast_reads WHERE agent_name = ?)''',
        (agent, agent))
    broadcast = cur.fetchone()[0]

    # Stand down flag
    cur.execute(\"SELECT value FROM flags WHERE key = 'stand_down'\")
    row = cur.fetchone()
    stand_down = row[0] == '1' if row else False

    # Retire flag
    cur.execute('SELECT agent_name FROM agent_retire WHERE agent_name = ?', (agent,))
    retire = cur.fetchone() is not None

    conn.close()

    print(json.dumps({
        'unread': direct + broadcast,
        'stand_down': stand_down,
        'retire': retire,
    }))
except Exception as e:
    print(json.dumps({'error': str(e)}), file=sys.stderr)
    sys.exit(2)
" 2>/dev/null)

    if [[ -z "$RESULT" ]]; then
        sleep "$INTERVAL"
        ELAPSED=$((ELAPSED + INTERVAL))
        if [[ "$TIMEOUT" -gt 0 && "$ELAPSED" -ge "$TIMEOUT" ]]; then
            exit 1
        fi
        continue
    fi

    # Parse result
    STAND_DOWN=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stand_down', False))" 2>/dev/null || echo "False")
    RETIRE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('retire', False))" 2>/dev/null || echo "False")
    UNREAD=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('unread', 0))" 2>/dev/null || echo "0")

    if [[ "$STAND_DOWN" == "True" || "$RETIRE" == "True" ]]; then
        echo "[poll.sh] stand_down/retire detected for $AGENT. Exiting." >&2
        exit 3
    fi

    if [[ "$UNREAD" -gt 0 ]]; then
        exit 0
    fi

    sleep "$INTERVAL"
    ELAPSED=$((ELAPSED + INTERVAL))

    if [[ "$TIMEOUT" -gt 0 && "$ELAPSED" -ge "$TIMEOUT" ]]; then
        exit 1
    fi
done
