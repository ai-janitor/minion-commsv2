"""Triggers — get_triggers, clear_moon_crash."""

from __future__ import annotations

import json

from minion_comms.auth import TRIGGER_WORDS
from minion_comms.db import get_db, now_iso


def get_triggers() -> dict[str, object]:
    return {
        "triggers": TRIGGER_WORDS,
        "notes": [
            "Include a trigger word in any send message. Comms recognizes it automatically.",
            "moon_crash auto-blocks all new task assignments.",
            "stand_down signals all daemons to exit gracefully.",
        ],
    }


def clear_moon_crash(agent_name: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can clear moon_crash. '{agent_name}' is '{row['agent_class']}'."}

        cursor.execute("SELECT value FROM flags WHERE key = 'moon_crash'")
        flag_row = cursor.fetchone()
        if not flag_row or flag_row["value"] != "1":
            return {"status": "noop", "note": "moon_crash is not currently active."}

        cursor.execute(
            "UPDATE flags SET value = '0', set_by = ?, set_at = ? WHERE key = 'moon_crash'",
            (agent_name, now),
        )
        conn.commit()
        return {"status": "cleared", "agent": agent_name}
    finally:
        conn.close()
