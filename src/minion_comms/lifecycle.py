"""Lifecycle — cold_start, fenix_down, debrief, end_session."""

from __future__ import annotations

import json
import os
from typing import Any

from minion_comms.auth import CLASS_BRIEFING_FILES, get_tools_for_class
from minion_comms.db import get_db, now_iso
from minion_comms.fs import read_content_file


def cold_start(agent_name: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name, agent_class FROM agents WHERE name = ?", (agent_name,))
        agent_row = cursor.fetchone()
        if not agent_row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered. Call register first."}

        agent_class = agent_row["agent_class"]
        result: dict[str, Any] = {"agent_name": agent_name, "agent_class": agent_class}

        # Active battle plan
        cursor.execute("SELECT * FROM battle_plan WHERE status = 'active' ORDER BY created_at DESC LIMIT 1")
        plan_row = cursor.fetchone()
        if plan_row:
            plan = dict(plan_row)
            plan["plan_content"] = read_content_file(plan.get("plan_file"))
            result["battle_plan"] = plan
        else:
            result["battle_plan"] = None

        # Recent raid log
        cursor.execute("SELECT * FROM raid_log ORDER BY created_at DESC LIMIT 20")
        raid_entries = []
        for row in cursor.fetchall():
            e = dict(row)
            e["entry_content"] = read_content_file(e.get("entry_file"))
            raid_entries.append(e)
        result["raid_log"] = raid_entries

        # Open tasks
        cursor.execute(
            "SELECT * FROM tasks WHERE status IN ('open', 'assigned', 'in_progress') ORDER BY created_at DESC"
        )
        result["open_tasks"] = [dict(row) for row in cursor.fetchall()]

        # Registered agents
        cursor.execute("SELECT name, agent_class, status, last_seen FROM agents ORDER BY last_seen DESC")
        result["agents"] = [dict(row) for row in cursor.fetchall()]

        # Briefing files
        result["briefing_files"] = CLASS_BRIEFING_FILES.get(agent_class, [])
        result["convention_files"] = {
            "intel": ".minion-comms/intel/",
            "traps": ".minion-comms/traps/",
            "code_map": ".minion-comms/CODE_MAP.md",
            "code_owners": ".minion-comms/CODE_OWNERS.md",
        }

        # Unconsumed fenix_down records
        cursor.execute(
            "SELECT * FROM fenix_down_records WHERE agent_name = ? AND consumed = 0 ORDER BY created_at DESC",
            (agent_name,),
        )
        fenix_records = [dict(row) for row in cursor.fetchall()]
        result["fenix_down_records"] = fenix_records

        if fenix_records:
            record_ids = [r["id"] for r in fenix_records]
            placeholders = ",".join(["?"] * len(record_ids))
            cursor.execute(
                f"UPDATE fenix_down_records SET consumed = 1 WHERE id IN ({placeholders})",
                record_ids,
            )

        # Tool catalog for this class
        result["tools"] = get_tools_for_class(agent_class)

        cursor.execute("UPDATE agents SET last_seen = ? WHERE name = ?", (now, agent_name))
        conn.commit()

        return result
    finally:
        conn.close()


def fenix_down(agent_name: str, files: str, manifest: str = "") -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (agent_name,))
        if not cursor.fetchone():
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}

        file_list = [f.strip() for f in files.split(",") if f.strip()]
        if not file_list:
            return {"error": "BLOCKED: No files provided. List the files you wrote this session."}

        files_json = json.dumps(file_list)

        cursor.execute(
            """INSERT INTO fenix_down_records (agent_name, files, manifest, consumed, created_at)
               VALUES (?, ?, ?, 0, ?)""",
            (agent_name, files_json, manifest or "", now),
        )
        record_id = cursor.lastrowid

        cursor.execute(
            "UPDATE agents SET status = 'phoenix_down', last_seen = ? WHERE name = ?",
            (now, agent_name),
        )
        conn.commit()

        return {
            "status": "recorded",
            "record_id": record_id,
            "agent": agent_name,
            "files_count": len(file_list),
        }
    finally:
        conn.close()


def debrief(agent_name: str, debrief_file: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can file a debrief. '{agent_name}' is '{row['agent_class']}'."}

        if not os.path.exists(debrief_file):
            return {"error": f"BLOCKED: Debrief file does not exist: {debrief_file}"}

        cursor.execute(
            """INSERT INTO raid_log (agent_name, entry_file, priority, created_at)
               VALUES (?, ?, 'critical', ?)""",
            (agent_name, debrief_file, now),
        )
        cursor.execute("UPDATE agents SET last_seen = ? WHERE name = ?", (now, agent_name))
        conn.commit()

        return {"status": "filed", "agent": agent_name, "debrief_file": debrief_file}
    finally:
        conn.close()


def end_session(agent_name: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can end the session. '{agent_name}' is '{row['agent_class']}'."}

        # Check for debrief via raid log entry files containing "DEBRIEF"
        cursor.execute(
            "SELECT COUNT(*) FROM raid_log WHERE priority = 'critical' AND agent_name = ?",
            (agent_name,),
        )
        # Actually check entry content for DEBRIEF FILED pattern
        cursor.execute("SELECT entry_file FROM raid_log WHERE priority = 'critical'")
        has_debrief = False
        for r in cursor.fetchall():
            # The debrief() function stores the debrief_file path directly as entry_file
            # We just check if any critical raid log entry is a debrief file
            if r["entry_file"] and os.path.exists(r["entry_file"]):
                has_debrief = True
                break

        if not has_debrief:
            return {"error": "BLOCKED: No debrief filed. Lead must call debrief before ending the session."}

        # Check for open tasks
        cursor.execute(
            "SELECT id, title, status, assigned_to FROM tasks WHERE status IN ('open', 'assigned', 'in_progress')"
        )
        open_tasks = [dict(row) for row in cursor.fetchall()]
        if open_tasks:
            task_summary = "; ".join(
                f"#{t['id']} {t['title']} ({t['status']})"
                for t in open_tasks
            )
            return {"error": f"BLOCKED: {len(open_tasks)} open task(s): {task_summary}"}

        # Mark active plan completed
        cursor.execute("SELECT id FROM battle_plan WHERE status = 'active' ORDER BY created_at DESC LIMIT 1")
        plan_row = cursor.fetchone()
        plan_summary = "No active battle plan."
        if plan_row:
            cursor.execute(
                "UPDATE battle_plan SET status = 'completed', updated_at = ? WHERE id = ?",
                (now, plan_row["id"]),
            )
            plan_summary = f"Battle plan #{plan_row['id']} marked completed."

        # Gather summary stats
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'closed'")
        closed_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM raid_log")
        log_count = cursor.fetchone()[0]
        cursor.execute("SELECT name, agent_class, status FROM agents ORDER BY name")
        agents = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            """INSERT INTO raid_log (agent_name, entry_file, priority, created_at)
               VALUES (?, 'SESSION_ENDED', 'critical', ?)""",
            (agent_name, now),
        )
        conn.commit()

        return {
            "status": "ended",
            "battle_plan": plan_summary,
            "tasks_closed": closed_count,
            "raid_log_entries": log_count,
            "agents": agents,
            "ended_by": agent_name,
            "ended_at": now,
        }
    finally:
        conn.close()
