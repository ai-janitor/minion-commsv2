"""Poll loop — replaces poll.sh with first-class Python.

Returns actionable content (messages + available tasks) in one response.
Exit codes (minion-swarm contract):
  0 — content delivered (messages and/or tasks)
  1 — timeout reached
  3 — stand_down/retire signal detected
"""

from __future__ import annotations

import os
import time
from typing import Any

from minion_comms.db import get_db, now_iso


def _fetch_messages(agent: str) -> list[dict[str, Any]]:
    """Fetch and mark-read all unread messages (direct + broadcast). Same as check-inbox."""
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute(
            "UPDATE agents SET last_seen = ?, last_inbox_check = ? WHERE name = ?",
            (now, now, agent),
        )

        # Direct messages
        cursor.execute(
            "SELECT * FROM messages WHERE to_agent = ? AND read_flag = 0", (agent,),
        )
        direct = [dict(r) for r in cursor.fetchall()]
        if direct:
            ids = [m["id"] for m in direct]
            cursor.execute(
                f"UPDATE messages SET read_flag = 1 WHERE id IN ({','.join('?' * len(ids))})", ids,
            )

        # Broadcasts
        cursor.execute(
            """SELECT * FROM messages WHERE to_agent = 'all'
               AND id NOT IN (SELECT message_id FROM broadcast_reads WHERE agent_name = ?)""",
            (agent,),
        )
        broadcasts = [dict(r) for r in cursor.fetchall()]
        for msg in broadcasts:
            cursor.execute(
                "INSERT OR IGNORE INTO broadcast_reads (agent_name, message_id) VALUES (?, ?)",
                (agent, msg["id"]),
            )

        conn.commit()

        all_msgs = direct + broadcasts
        all_msgs.sort(key=lambda x: x.get("timestamp", ""))

        # Inline content from files
        for msg in all_msgs:
            cf = msg.get("content_file")
            if cf and os.path.exists(cf):
                with open(cf) as f:
                    msg["content"] = f.read()
            else:
                msg["content"] = ""
            if msg.get("is_cc"):
                msg["cc_note"] = f"[CC] originally to: {msg.get('cc_original_to', 'unknown')}"

        return all_msgs
    finally:
        conn.close()


def _find_available_tasks(agent: str) -> list[dict[str, Any]]:
    """Find claimable tasks for this agent without claiming them."""
    from minion_comms.flow_bridge import active_statuses

    conn = get_db()
    cursor = conn.cursor()
    try:
        # moon_crash blocks
        cursor.execute("SELECT value FROM flags WHERE key = 'moon_crash'")
        mc = cursor.fetchone()
        if mc and mc["value"] == "1":
            return []

        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent,))
        row = cursor.fetchone()
        if not row:
            return []
        agent_class = row["agent_class"]

        candidates: list[dict[str, Any]] = []

        # P1: already assigned to agent
        actives = active_statuses()
        cursor.execute(
            """SELECT id, title, task_file, status, class_required, blocked_by
               FROM tasks WHERE assigned_to = ? AND status IN ({})
               ORDER BY created_at ASC LIMIT 10""".format(
                ",".join("?" for _ in actives)
            ),
            (agent, *actives),
        )
        candidates.extend(dict(r) for r in cursor.fetchall())

        # P2: open tasks matching class
        if not candidates:
            cursor.execute(
                """SELECT id, title, task_file, status, class_required, blocked_by
                   FROM tasks WHERE status = 'open' AND class_required = ? AND assigned_to IS NULL
                   ORDER BY created_at ASC LIMIT 10""",
                (agent_class,),
            )
            candidates.extend(dict(r) for r in cursor.fetchall())

        # P3: fixed tasks for reviewers
        if not candidates and agent_class in ("recon", "oracle"):
            cursor.execute(
                """SELECT id, title, task_file, status, class_required, blocked_by
                   FROM tasks WHERE status = 'fixed' AND assigned_to IS NULL
                   ORDER BY created_at ASC LIMIT 10"""
            )
            candidates.extend(dict(r) for r in cursor.fetchall())

        # P4: verified tasks for testers
        if not candidates and agent_class == "recon":
            cursor.execute(
                """SELECT id, title, task_file, status, class_required, blocked_by
                   FROM tasks WHERE status = 'verified' AND assigned_to IS NULL
                   ORDER BY created_at ASC LIMIT 10"""
            )
            candidates.extend(dict(r) for r in cursor.fetchall())

        # Filter blocked
        result = []
        for task in candidates:
            blocked_by = task.get("blocked_by")
            if blocked_by:
                blocker_ids = [int(x.strip()) for x in blocked_by.split(",") if x.strip()]
                placeholders = ",".join("?" for _ in blocker_ids)
                cursor.execute(
                    f"SELECT COUNT(*) FROM tasks WHERE id IN ({placeholders}) AND status != 'closed'",
                    blocker_ids,
                )
                if cursor.fetchone()[0] > 0:
                    continue
            result.append({
                "task_id": task["id"],
                "title": task["title"],
                "status": task["status"],
                "task_file": task["task_file"],
                "claim_cmd": f"minion pull-task --agent {agent} --task-id {task['id']}",
            })
        return result
    finally:
        conn.close()


def _check_signals(agent: str) -> str | None:
    """Check stand_down / retire. Returns signal name or None."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM flags WHERE key = 'stand_down'")
        row = cur.fetchone()
        if row and row[0] == "1":
            return "stand_down"
        cur.execute("SELECT agent_name FROM agent_retire WHERE agent_name = ?", (agent,))
        if cur.fetchone():
            return "retire"
        return None
    finally:
        conn.close()


def poll_loop(agent: str, interval: int = 5, timeout: int = 0) -> dict[str, Any]:
    """Block until messages/tasks arrive, then return them.

    Returns dict with:
      - exit_code: 0 (content), 1 (timeout), 3 (signal)
      - messages: list of message dicts (if any)
      - tasks: list of available task dicts (if any)
      - signal: "stand_down" or "retire" (if exit_code 3)
      - transport_hint: restart reminder for terminal agents
    """
    elapsed = 0

    while True:
        # Check signals first
        signal = _check_signals(agent)
        if signal:
            return {
                "exit_code": 3,
                "signal": signal,
                "action": "Do NOT restart polling. The party has been dismissed."
                if signal == "stand_down"
                else "Do NOT restart polling. You have been retired from the party.",
            }

        # Check for messages (peek — don't consume yet)
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM messages WHERE to_agent = ? AND read_flag = 0", (agent,))
            direct = cur.fetchone()[0]
            cur.execute(
                """SELECT COUNT(*) FROM messages
                   WHERE to_agent = 'all' AND from_agent != ?
                   AND id NOT IN (SELECT message_id FROM broadcast_reads WHERE agent_name = ?)""",
                (agent, agent),
            )
            broadcast = cur.fetchone()[0]
            has_messages = (direct + broadcast) > 0

            # Get transport
            cur.execute("SELECT transport FROM agents WHERE name = ?", (agent,))
            row = cur.fetchone()
            transport = row["transport"] if row else "terminal"
        finally:
            conn.close()

        # Find available tasks
        available_tasks = _find_available_tasks(agent)

        if has_messages or available_tasks:
            # Consume messages
            messages = _fetch_messages(agent) if has_messages else []

            result: dict[str, Any] = {"exit_code": 0}
            if messages:
                result["messages"] = messages
            if available_tasks:
                result["tasks"] = available_tasks
            if transport == "terminal":
                result["transport_hint"] = (
                    f"RESTART POLLING: Run `minion poll --agent {agent}` as a background task again. "
                    f"Do NOT add --timeout. It blocks forever until the next message arrives."
                )
            return result

        time.sleep(interval)
        elapsed += interval

        if timeout > 0 and elapsed >= timeout:
            return {"exit_code": 1}
