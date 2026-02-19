"""Core Comms — register, deregister, rename, set_status, set_context,
who, send, check_inbox, get_history, purge_inbox."""

from __future__ import annotations

import datetime
import json

from minion_comms.auth import CLASS_MODEL_WHITELIST, VALID_CLASSES, get_tools_for_class
from minion_comms.db import (
    enrich_agent_row,
    format_trigger_codebook,
    get_db,
    get_lead,
    hp_summary,
    load_onboarding,
    now_iso,
    scan_triggers,
    staleness_check,
)
from minion_comms.fs import (
    atomic_write_file,
    message_file_path,
    read_content_file,
)


def register(
    agent_name: str,
    agent_class: str,
    model: str = "",
    description: str = "",
    transport: str = "terminal",
) -> dict[str, object]:
    if transport not in ("terminal", "daemon"):
        return {"error": f"Invalid transport '{transport}'. Must be 'terminal' or 'daemon'."}
    if agent_class not in VALID_CLASSES:
        return {"error": f"Unknown class '{agent_class}'. Valid: {', '.join(sorted(VALID_CLASSES))}"}

    allowed_models = CLASS_MODEL_WHITELIST.get(agent_class, set())
    if allowed_models and model and model not in allowed_models:
        return {"error": f"Model '{model}' not allowed for class '{agent_class}'. Allowed: {', '.join(sorted(allowed_models))}"}

    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute(
            """INSERT INTO agents
                (name, agent_class, model, registered_at, last_seen, description, status, transport)
            VALUES (?, ?, ?, ?, ?, ?, 'waiting for work', ?)
            ON CONFLICT(name) DO UPDATE SET
                last_seen   = excluded.last_seen,
                agent_class = excluded.agent_class,
                model       = COALESCE(NULLIF(excluded.model, ''), agents.model),
                description = COALESCE(NULLIF(excluded.description, ''), agents.description),
                transport   = excluded.transport,
                status      = 'waiting for work'
            """,
            (agent_name, agent_class, model or None, now, now, description or None, transport),
        )

        # Auto-mark old broadcasts as read
        cutoff = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        cursor.execute(
            """INSERT OR IGNORE INTO broadcast_reads (agent_name, message_id)
               SELECT ?, id FROM messages WHERE to_agent = 'all' AND timestamp < ?""",
            (agent_name, cutoff),
        )

        # Clear retire flag for re-spawned agents
        cursor.execute("DELETE FROM agent_retire WHERE agent_name = ?", (agent_name,))
        conn.commit()

        result: dict[str, object] = {
            "status": "registered",
            "agent": agent_name,
            "class": agent_class,
        }
        if model:
            result["model"] = model
        if description:
            result["description"] = description

        onboarding = load_onboarding(agent_class)
        if onboarding:
            result["onboarding"] = onboarding

        result["triggers"] = format_trigger_codebook()
        result["tools"] = get_tools_for_class(agent_class)
        if transport == "terminal":
            result["playbook"] = {
                "type": "terminal",
                "steps": [
                    "Start background inbox polling: poll.sh " + agent_name + " &",
                    "Read your protocol doc: ~/.minion-comms/docs/protocol-" + agent_class + ".md",
                    "Set your context: minion set-context --agent " + agent_name + " --context 'loaded'",
                    "On compaction: call minion cold-start --agent " + agent_name + " to recover state",
                ],
            }
        else:
            result["playbook"] = {
                "type": "daemon",
                "steps": [
                    "The watcher manages your context — it re-injects tools and state after compaction",
                    "Just check inbox and work: minion check-inbox --agent " + agent_name,
                ],
            }
        return result
    finally:
        conn.close()


def deregister(agent_name: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (agent_name,))
        if not cursor.fetchone():
            return {"error": f"Agent '{agent_name}' not found."}

        # Release file claims
        cursor.execute("SELECT file_path FROM file_claims WHERE agent_name = ?", (agent_name,))
        claimed_files = [row["file_path"] for row in cursor.fetchall()]
        waitlist_notes: list[str] = []
        for fp in claimed_files:
            cursor.execute("DELETE FROM file_claims WHERE file_path = ?", (fp,))
            cursor.execute(
                "SELECT agent_name FROM file_waitlist WHERE file_path = ? ORDER BY added_at ASC LIMIT 1",
                (fp,),
            )
            waiter = cursor.fetchone()
            if waiter:
                waitlist_notes.append(f"{fp} -> {waiter['agent_name']} waiting")
        cursor.execute("DELETE FROM file_waitlist WHERE agent_name = ?", (agent_name,))
        cursor.execute("DELETE FROM agents WHERE name = ?", (agent_name,))
        conn.commit()

        result: dict[str, object] = {
            "status": "deregistered",
            "agent": agent_name,
            "released_claims": len(claimed_files),
        }
        if waitlist_notes:
            result["waitlist_notify"] = waitlist_notes
        return result
    finally:
        conn.close()


def rename(old_name: str, new_name: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (old_name,))
        if not cursor.fetchone():
            return {"error": f"Agent '{old_name}' not found."}
        cursor.execute("SELECT name FROM agents WHERE name = ?", (new_name,))
        if cursor.fetchone():
            return {"error": f"Agent '{new_name}' already exists."}

        cursor.execute("UPDATE agents SET name = ? WHERE name = ?", (new_name, old_name))
        cursor.execute("UPDATE messages SET from_agent = ? WHERE from_agent = ?", (new_name, old_name))
        cursor.execute("UPDATE messages SET to_agent = ? WHERE to_agent = ?", (new_name, old_name))
        cursor.execute("UPDATE messages SET cc_original_to = ? WHERE cc_original_to = ?", (new_name, old_name))
        cursor.execute("UPDATE broadcast_reads SET agent_name = ? WHERE agent_name = ?", (new_name, old_name))
        conn.commit()
        return {"status": "renamed", "old": old_name, "new": new_name}
    finally:
        conn.close()


def set_status(agent_name: str, status: str) -> dict[str, object]:
    conn = get_db()
    now = now_iso()
    try:
        conn.execute(
            "UPDATE agents SET status = ?, last_seen = ? WHERE name = ?",
            (status, now, agent_name),
        )
        conn.commit()
        return {"status": "ok", "agent": agent_name, "new_status": status}
    finally:
        conn.close()


def set_context(
    agent_name: str,
    context: str,
    tokens_used: int = 0,
    tokens_limit: int = 0,
) -> dict[str, object]:
    conn = get_db()
    now = now_iso()
    try:
        conn.execute(
            """UPDATE agents
               SET context_summary = ?,
                   context_updated_at = ?,
                   last_seen = ?
               WHERE name = ?""",
            (context, now, now, agent_name),
        )
        conn.commit()

        result: dict[str, object] = {"status": "ok", "agent": agent_name, "context": context}
        if tokens_used and tokens_limit:
            result["hp"] = hp_summary(tokens_used, None, tokens_limit)
        return result
    finally:
        conn.close()


def who() -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.datetime.now()
    try:
        cursor.execute("SELECT * FROM agents ORDER BY last_seen DESC")
        agents = [enrich_agent_row(row, now) for row in cursor.fetchall()]
        return {"agents": agents}
    finally:
        conn.close()


def send(
    from_agent: str,
    to_agent: str,
    message: str,
    cc: str = "",
) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        # Inbox discipline: must read before sending
        cursor.execute(
            "SELECT COUNT(*) FROM messages WHERE to_agent = ? AND read_flag = 0",
            (from_agent,),
        )
        unread_direct = cursor.fetchone()[0]

        cursor.execute(
            """SELECT COUNT(*) FROM messages
               WHERE to_agent = 'all' AND from_agent != ?
               AND id NOT IN (SELECT message_id FROM broadcast_reads WHERE agent_name = ?)""",
            (from_agent, from_agent),
        )
        unread_broadcast = cursor.fetchone()[0]

        unread = unread_direct + unread_broadcast
        if unread > 0:
            return {"error": f"BLOCKED: You have {unread} unread message(s). Call check-inbox first."}

        # Battle plan enforcement
        cursor.execute("SELECT COUNT(*) FROM battle_plan WHERE status = 'active'")
        if cursor.fetchone()[0] == 0:
            return {"error": "BLOCKED: No active battle plan. Lead must call set-battle-plan first."}

        # Context freshness
        is_stale, stale_msg = staleness_check(cursor, from_agent)
        if is_stale:
            return {"error": stale_msg}

        # Auto-register unknown senders
        cursor.execute(
            "INSERT OR IGNORE INTO agents (name, agent_class, registered_at, last_seen) VALUES (?, 'coder', ?, ?)",
            (from_agent, now, now),
        )

        # Write message body to filesystem
        content_file = message_file_path(to_agent, from_agent)
        atomic_write_file(content_file, message)

        # Insert metadata into DB
        cursor.execute(
            "INSERT INTO messages (from_agent, to_agent, content_file, timestamp, read_flag, is_cc) VALUES (?, ?, ?, ?, 0, 0)",
            (from_agent, to_agent, content_file, now),
        )

        # Build CC list: explicit + auto-CC lead
        cc_agents = [a.strip() for a in cc.split(",") if a.strip()] if cc else []

        lead_name = get_lead(cursor)
        if lead_name and from_agent != lead_name and to_agent != lead_name and lead_name not in cc_agents:
            cc_agents.append(lead_name)

        for cc_agent in cc_agents:
            if cc_agent != to_agent:
                cc_file = message_file_path(cc_agent, from_agent, "cc")
                atomic_write_file(cc_file, message)
                cursor.execute(
                    """INSERT INTO messages
                       (from_agent, to_agent, content_file, timestamp, read_flag, is_cc, cc_original_to)
                       VALUES (?, ?, ?, ?, 0, 1, ?)""",
                    (from_agent, cc_agent, cc_file, now, to_agent),
                )

        # Update sender's last_seen
        cursor.execute("UPDATE agents SET last_seen = ? WHERE name = ?", (now, from_agent))

        # Trigger word detection
        triggers_found = scan_triggers(message)

        if "moon_crash" in triggers_found:
            cursor.execute(
                """INSERT INTO flags (key, value, set_by, set_at)
                   VALUES ('moon_crash', '1', ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = '1', set_by = excluded.set_by, set_at = excluded.set_at""",
                (from_agent, now),
            )

        if "stand_down" in triggers_found:
            cursor.execute(
                """INSERT INTO flags (key, value, set_by, set_at)
                   VALUES ('stand_down', '1', ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = '1', set_by = excluded.set_by, set_at = excluded.set_at""",
                (from_agent, now),
            )

        conn.commit()

        result: dict[str, object] = {
            "status": "sent",
            "from": from_agent,
            "to": to_agent,
        }
        if cc_agents:
            result["cc"] = cc_agents
        if triggers_found:
            result["triggers"] = triggers_found

        # Transport-based poll reminder
        cursor.execute("SELECT transport FROM agents WHERE name = ?", (from_agent,))
        sender_row = cursor.fetchone()
        if sender_row and sender_row["transport"] == "terminal":
            result["reminder"] = "Ensure poll.sh is running so you don't miss replies."

        return result
    finally:
        conn.close()


def check_inbox(agent_name: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute(
            "UPDATE agents SET last_seen = ?, last_inbox_check = ? WHERE name = ?",
            (now, now, agent_name),
        )

        # Direct messages
        cursor.execute(
            "SELECT * FROM messages WHERE to_agent = ? AND read_flag = 0",
            (agent_name,),
        )
        direct_msgs = [dict(row) for row in cursor.fetchall()]

        if direct_msgs:
            ids = [m["id"] for m in direct_msgs]
            placeholders = ",".join(["?"] * len(ids))
            cursor.execute(f"UPDATE messages SET read_flag = 1 WHERE id IN ({placeholders})", ids)

        # Broadcast messages
        cursor.execute(
            """SELECT * FROM messages
               WHERE to_agent = 'all'
               AND id NOT IN (SELECT message_id FROM broadcast_reads WHERE agent_name = ?)""",
            (agent_name,),
        )
        broadcast_msgs = [dict(row) for row in cursor.fetchall()]

        for msg in broadcast_msgs:
            cursor.execute(
                "INSERT OR IGNORE INTO broadcast_reads (agent_name, message_id) VALUES (?, ?)",
                (agent_name, msg["id"]),
            )

        conn.commit()

        all_messages = direct_msgs + broadcast_msgs
        all_messages.sort(key=lambda x: x.get("timestamp", ""))

        # Inline content from files for convenience
        for msg in all_messages:
            msg["content"] = read_content_file(msg.get("content_file"))
            if msg.get("is_cc"):
                msg["cc_note"] = f"[CC] originally to: {msg.get('cc_original_to', 'unknown')}"

        _, stale_msg = staleness_check(cursor, agent_name)

        result: dict[str, object] = {"messages": all_messages}
        if stale_msg:
            result["warning"] = stale_msg.replace("BLOCKED: ", "")
        return result
    finally:
        conn.close()


def get_history(count: int = 20) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?", (count,))
        msgs = [dict(row) for row in cursor.fetchall()]
        for msg in msgs:
            msg["content"] = read_content_file(msg.get("content_file"))
        return {"messages": msgs[::-1]}
    finally:
        conn.close()


def purge_inbox(agent_name: str, older_than_hours: int = 2) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    cutoff = (datetime.datetime.now() - datetime.timedelta(hours=older_than_hours)).isoformat()
    try:
        cursor.execute(
            "DELETE FROM messages WHERE to_agent = ? AND timestamp < ?",
            (agent_name, cutoff),
        )
        deleted = cursor.rowcount

        cursor.execute(
            """INSERT OR IGNORE INTO broadcast_reads (agent_name, message_id)
               SELECT ?, id FROM messages WHERE to_agent = 'all' AND timestamp < ?""",
            (agent_name, cutoff),
        )
        dismissed = cursor.rowcount

        cursor.execute(
            """DELETE FROM broadcast_reads
               WHERE agent_name = ?
               AND message_id NOT IN (SELECT id FROM messages)""",
            (agent_name,),
        )
        conn.commit()

        return {
            "status": "purged",
            "agent": agent_name,
            "deleted_direct": deleted,
            "dismissed_broadcasts": dismissed,
            "older_than_hours": older_than_hours,
        }
    finally:
        conn.close()
