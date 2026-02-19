"""Stand down and retire — crew dismissal and individual agent retirement."""

from __future__ import annotations

import os
import subprocess

from minion_comms.comms import deregister
from minion_comms.db import get_db, now_iso
from minion_comms.crew._tmux import close_terminal_by_title, kill_all_crews, kill_tmux_pane_by_title


def stand_down(agent_name: str, crew: str = "") -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can stand_down. '{agent_name}' is '{row['agent_class']}'."}

        cursor.execute(
            """INSERT INTO flags (key, value, set_by, set_at)
               VALUES ('stand_down', '1', ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = '1', set_by = excluded.set_by, set_at = excluded.set_at""",
            (agent_name, now),
        )
        conn.commit()
    finally:
        conn.close()

    if crew:
        config_path = os.path.expanduser(f"~/.minion-swarm/{crew}.yaml")
        if os.path.isfile(config_path):
            subprocess.run(["minion-swarm", "stop", "--config", config_path], capture_output=True)
        close_terminal_by_title(f"workers:crew-{crew}")
        close_terminal_by_title(f"lead:")
        subprocess.run(["tmux", "kill-session", "-t", f"crew-{crew}"], capture_output=True)
        return {"status": "dismissed", "crew": crew}
    else:
        kill_all_crews()
        return {"status": "dismissed", "crew": "all"}


def retire_agent(agent_name: str, requesting_agent: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (requesting_agent,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{requesting_agent}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can retire agents. '{requesting_agent}' is '{row['agent_class']}'."}

        cursor.execute(
            """INSERT INTO agent_retire (agent_name, set_at, set_by)
               VALUES (?, ?, ?)
               ON CONFLICT(agent_name) DO UPDATE SET set_at = excluded.set_at, set_by = excluded.set_by""",
            (agent_name, now, requesting_agent),
        )
        conn.commit()
    finally:
        conn.close()

    deregister(agent_name)
    kill_tmux_pane_by_title(agent_name)

    return {"status": "retired", "agent": agent_name, "by": requesting_agent}
