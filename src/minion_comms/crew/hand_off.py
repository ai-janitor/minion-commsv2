"""Zone handoff — retiring agent bestows zone to replacements."""

from __future__ import annotations

from minion_comms.db import get_db, now_iso


def hand_off_zone(
    from_agent: str,
    to_agents: str,
    zone: str,
) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (from_agent,))
        if not cursor.fetchone():
            return {"error": f"BLOCKED: Agent '{from_agent}' not registered."}

        targets = [a.strip() for a in to_agents.split(",") if a.strip()]
        if not targets:
            return {"error": "BLOCKED: No target agents specified."}

        missing = []
        for t in targets:
            cursor.execute("SELECT name FROM agents WHERE name = ?", (t,))
            if not cursor.fetchone():
                missing.append(t)
        if missing:
            return {"error": f"BLOCKED: Agents not registered: {', '.join(missing)}"}

        for t in targets:
            cursor.execute(
                "UPDATE agents SET current_zone = ?, last_seen = ? WHERE name = ?",
                (zone, now, t),
            )

        cursor.execute(
            "UPDATE agents SET current_zone = NULL, last_seen = ? WHERE name = ?",
            (now, from_agent),
        )

        from minion_comms.fs import atomic_write_file, raid_log_file_path
        entry = f"ZONE HANDOFF: {from_agent} → {', '.join(targets)} | zone: {zone}"
        entry_file = raid_log_file_path(from_agent, "high")
        atomic_write_file(entry_file, entry)

        cursor.execute(
            """INSERT INTO raid_log (agent_name, entry_file, priority, created_at)
               VALUES (?, ?, 'high', ?)""",
            (from_agent, entry_file, now),
        )

        conn.commit()

        return {
            "status": "handed_off",
            "from": from_agent,
            "to": targets,
            "zone": zone,
        }
    finally:
        conn.close()
