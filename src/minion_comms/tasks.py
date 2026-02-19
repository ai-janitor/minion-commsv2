"""Task System — create, assign, update, list, get, submit_result, close."""

from __future__ import annotations

import json
import os
from typing import Any

from minion_comms.auth import TASK_STATUSES
from minion_comms.db import get_db, now_iso, staleness_check


def create_task(
    agent_name: str,
    title: str,
    task_file: str,
    project: str = "",
    zone: str = "",
    blocked_by: str = "",
) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can create tasks. '{agent_name}' is '{row['agent_class']}'."}

        cursor.execute("SELECT COUNT(*) FROM battle_plan WHERE status = 'active'")
        if cursor.fetchone()[0] == 0:
            return {"error": "BLOCKED: No active battle plan. Lead must call set-battle-plan first."}

        if not os.path.exists(task_file):
            return {"error": f"BLOCKED: Task file does not exist: {task_file}"}

        blocker_ids: list[int] = []
        if blocked_by:
            for raw_id in blocked_by.split(","):
                raw_id = raw_id.strip()
                if not raw_id:
                    continue
                try:
                    tid = int(raw_id)
                except ValueError:
                    return {"error": f"BLOCKED: Invalid task ID in blocked_by: '{raw_id}'."}
                cursor.execute("SELECT id FROM tasks WHERE id = ?", (tid,))
                if not cursor.fetchone():
                    return {"error": f"BLOCKED: blocked_by task #{tid} does not exist."}
                blocker_ids.append(tid)

        blocked_by_str = ",".join(str(i) for i in blocker_ids) if blocker_ids else None

        cursor.execute(
            """INSERT INTO tasks
               (title, task_file, project, zone, status, blocked_by,
                created_by, activity_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'open', ?, ?, 0, ?, ?)""",
            (title, task_file, project or None, zone or None, blocked_by_str, agent_name, now, now),
        )
        task_id = cursor.lastrowid
        conn.commit()

        result: dict[str, object] = {"status": "created", "task_id": task_id, "title": title}
        if blocked_by_str:
            result["blocked_by"] = blocker_ids
        return result
    finally:
        conn.close()


def assign_task(agent_name: str, task_id: int, assigned_to: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        # moon_crash blocks assignments
        cursor.execute("SELECT value, set_by, set_at FROM flags WHERE key = 'moon_crash'")
        mc_row = cursor.fetchone()
        if mc_row and mc_row["value"] == "1":
            return {"error": f"BLOCKED: moon_crash active — no new assignments. (set by {mc_row['set_by']} at {mc_row['set_at']})"}

        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can assign tasks. '{agent_name}' is '{row['agent_class']}'."}

        cursor.execute("SELECT name FROM agents WHERE name = ?", (assigned_to,))
        if not cursor.fetchone():
            return {"error": f"BLOCKED: Agent '{assigned_to}' not registered."}

        cursor.execute("SELECT id, status FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        if not task_row:
            return {"error": f"Task #{task_id} not found."}
        if task_row["status"] == "closed":
            return {"error": f"BLOCKED: Task #{task_id} is closed."}

        cursor.execute(
            "UPDATE tasks SET assigned_to = ?, status = 'assigned', updated_at = ? WHERE id = ?",
            (assigned_to, now, task_id),
        )
        conn.commit()
        return {"status": "assigned", "task_id": task_id, "assigned_to": assigned_to}
    finally:
        conn.close()


def update_task(
    agent_name: str,
    task_id: int,
    status: str = "",
    progress: str = "",
    files: str = "",
) -> dict[str, object]:
    if status and status not in TASK_STATUSES:
        return {"error": f"Invalid status '{status}'. Valid: {', '.join(sorted(TASK_STATUSES))}"}
    if status == "closed":
        return {"error": "BLOCKED: Cannot set status to 'closed' via update-task. Use close-task."}

    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (agent_name,))
        if not cursor.fetchone():
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}

        cursor.execute(
            "SELECT id, status, activity_count, title FROM tasks WHERE id = ?",
            (task_id,),
        )
        task_row = cursor.fetchone()
        if not task_row:
            return {"error": f"Task #{task_id} not found."}
        if task_row["status"] == "closed":
            return {"error": f"BLOCKED: Task #{task_id} is closed."}

        fields = ["activity_count = activity_count + 1", "updated_at = ?"]
        params: list[str | int] = [now]

        if status:
            fields.append("status = ?")
            params.append(status)
        if progress:
            fields.append("progress = ?")
            params.append(progress)
        if files:
            fields.append("files = ?")
            params.append(files)

        params.append(task_id)
        cursor.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", params)

        cursor.execute("SELECT activity_count FROM tasks WHERE id = ?", (task_id,))
        new_count = cursor.fetchone()["activity_count"]

        cursor.execute("UPDATE agents SET last_seen = ? WHERE name = ?", (now, agent_name))
        conn.commit()

        result: dict[str, object] = {
            "status": "updated",
            "task_id": task_id,
            "activity_count": new_count,
        }
        if status:
            result["new_status"] = status
        if new_count >= 4:
            result["warning"] = f"Activity count at {new_count} — this fight is dragging. Consider reassessing."

        _, stale_msg = staleness_check(cursor, agent_name)
        if stale_msg:
            result["staleness_warning"] = stale_msg.replace("BLOCKED: ", "")

        return result
    finally:
        conn.close()


def get_tasks(
    status: str = "",
    project: str = "",
    zone: str = "",
    assigned_to: str = "",
    count: int = 50,
) -> dict[str, object]:
    if status and status not in TASK_STATUSES:
        return {"error": f"Invalid status '{status}'. Valid: {', '.join(sorted(TASK_STATUSES))}"}

    conn = get_db()
    cursor = conn.cursor()
    try:
        query = "SELECT * FROM tasks WHERE 1=1"
        params: list[str | int] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        else:
            query += " AND status IN ('open', 'assigned', 'in_progress')"

        if project:
            query += " AND project = ?"
            params.append(project)
        if zone:
            query += " AND zone = ?"
            params.append(zone)
        if assigned_to:
            query += " AND assigned_to = ?"
            params.append(assigned_to)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(count)

        cursor.execute(query, params)
        tasks_list = [dict(row) for row in cursor.fetchall()]
        return {"tasks": tasks_list}
    finally:
        conn.close()


def get_task(task_id: int) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"Task #{task_id} not found."}
        return {"task": dict(row)}
    finally:
        conn.close()


def submit_result(agent_name: str, task_id: int, result_file: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (agent_name,))
        if not cursor.fetchone():
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}

        cursor.execute("SELECT id, status, title FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        if not task_row:
            return {"error": f"Task #{task_id} not found."}

        if not os.path.exists(result_file):
            return {"error": f"BLOCKED: Result file does not exist: {result_file}"}

        cursor.execute(
            "UPDATE tasks SET result_file = ?, updated_at = ? WHERE id = ?",
            (result_file, now, task_id),
        )
        cursor.execute("UPDATE agents SET last_seen = ? WHERE name = ?", (now, agent_name))
        conn.commit()

        return {"status": "submitted", "task_id": task_id, "result_file": result_file}
    finally:
        conn.close()


def close_task(agent_name: str, task_id: int) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can close tasks. '{agent_name}' is '{row['agent_class']}'."}

        cursor.execute("SELECT id, status, result_file, title FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        if not task_row:
            return {"error": f"Task #{task_id} not found."}
        if task_row["status"] == "closed":
            return {"error": f"Task #{task_id} is already closed."}
        if not task_row["result_file"]:
            return {"error": f"BLOCKED: Task #{task_id} has no result file. Agent must call submit-result first."}

        cursor.execute(
            "UPDATE tasks SET status = 'closed', updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        conn.commit()
        return {"status": "closed", "task_id": task_id, "title": task_row["title"]}
    finally:
        conn.close()
