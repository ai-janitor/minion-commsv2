"""War Room — battle plans and raid log."""

from __future__ import annotations

import json
import os

from minion_comms.auth import BATTLE_PLAN_STATUSES, RAID_LOG_PRIORITIES
from minion_comms.db import get_db, now_iso
from minion_comms.fs import (
    atomic_write_file,
    battle_plan_file_path,
    raid_log_file_path,
    read_content_file,
)


def set_battle_plan(agent_name: str, plan: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can set the battle plan. '{agent_name}' is '{row['agent_class']}'."}

        # Supersede previous active plans
        cursor.execute(
            "UPDATE battle_plan SET status = 'superseded', updated_at = ? WHERE status = 'active'",
            (now,),
        )

        # Write plan to filesystem
        plan_file = battle_plan_file_path(agent_name)
        atomic_write_file(plan_file, plan)

        cursor.execute(
            """INSERT INTO battle_plan (set_by, plan_file, status, created_at, updated_at)
               VALUES (?, ?, 'active', ?, ?)""",
            (agent_name, plan_file, now, now),
        )
        plan_id = cursor.lastrowid
        conn.commit()

        return {"status": "active", "plan_id": plan_id, "set_by": agent_name, "plan_file": plan_file}
    finally:
        conn.close()


def get_battle_plan(status: str = "active") -> dict[str, object]:
    if status not in BATTLE_PLAN_STATUSES:
        return {"error": f"Invalid status '{status}'. Valid: {', '.join(sorted(BATTLE_PLAN_STATUSES))}"}

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT * FROM battle_plan WHERE status = ? ORDER BY created_at DESC",
            (status,),
        )
        plans = []
        for row in cursor.fetchall():
            p = dict(row)
            p["plan_content"] = read_content_file(p.get("plan_file"))
            plans.append(p)

        if not plans:
            return {"plans": [], "note": f"No battle plans with status '{status}'."}
        return {"plans": plans}
    finally:
        conn.close()


def update_battle_plan_status(agent_name: str, plan_id: int, status: str) -> dict[str, object]:
    if status not in BATTLE_PLAN_STATUSES:
        return {"error": f"Invalid status '{status}'. Valid: {', '.join(sorted(BATTLE_PLAN_STATUSES))}"}

    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can update battle plan status. '{agent_name}' is '{row['agent_class']}'."}

        cursor.execute("SELECT id, status FROM battle_plan WHERE id = ?", (plan_id,))
        plan_row = cursor.fetchone()
        if not plan_row:
            return {"error": f"Battle plan #{plan_id} not found."}

        old_status = plan_row["status"]
        cursor.execute(
            "UPDATE battle_plan SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, plan_id),
        )
        conn.commit()
        return {"status": "updated", "plan_id": plan_id, "old_status": old_status, "new_status": status}
    finally:
        conn.close()


def log_raid(agent_name: str, entry: str, priority: str = "normal") -> dict[str, object]:
    if priority not in RAID_LOG_PRIORITIES:
        return {"error": f"Invalid priority '{priority}'. Valid: {', '.join(sorted(RAID_LOG_PRIORITIES))}"}

    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (agent_name,))
        if not cursor.fetchone():
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}

        # Write entry to filesystem
        entry_file = raid_log_file_path(agent_name, priority)
        atomic_write_file(entry_file, entry)

        cursor.execute(
            """INSERT INTO raid_log (agent_name, entry_file, priority, created_at)
               VALUES (?, ?, ?, ?)""",
            (agent_name, entry_file, priority, now),
        )
        log_id = cursor.lastrowid

        cursor.execute("UPDATE agents SET last_seen = ? WHERE name = ?", (now, agent_name))
        conn.commit()

        return {"status": "logged", "log_id": log_id, "agent": agent_name, "priority": priority}
    finally:
        conn.close()


def get_raid_log(
    priority: str = "",
    count: int = 20,
    agent_name: str = "",
) -> dict[str, object]:
    if priority and priority not in RAID_LOG_PRIORITIES:
        return {"error": f"Invalid priority '{priority}'. Valid: {', '.join(sorted(RAID_LOG_PRIORITIES))}"}

    conn = get_db()
    cursor = conn.cursor()
    try:
        query = "SELECT * FROM raid_log WHERE 1=1"
        params: list[str | int] = []

        if priority:
            query += " AND priority = ?"
            params.append(priority)
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(count)

        cursor.execute(query, params)
        entries = []
        for row in cursor.fetchall():
            e = dict(row)
            e["entry_content"] = read_content_file(e.get("entry_file"))
            entries.append(e)

        return {"entries": entries}
    finally:
        conn.close()
