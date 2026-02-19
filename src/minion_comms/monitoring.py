"""Monitoring — party_status, check_activity, check_freshness, sitrep, update_hp."""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

from minion_comms.db import enrich_agent_row, get_db, now_iso
from minion_comms.fs import read_content_file


def _safe_mtime(file_path: str) -> str | None:
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.datetime.fromtimestamp(mtime).isoformat()
    except OSError:
        return None


def _agent_judgment(
    last_seen: str | None,
    last_task_update: str | None,
    file_mtimes: list[str | None],
) -> str:
    now = datetime.datetime.now()

    for mt in file_mtimes:
        if mt:
            try:
                mtime_dt = datetime.datetime.fromisoformat(mt)
                if (now - mtime_dt).total_seconds() < 5 * 60:
                    return "active"
            except ValueError:
                pass

    if last_seen:
        try:
            ls = datetime.datetime.fromisoformat(last_seen)
            age_min = (now - ls).total_seconds() / 60
            if age_min < 5:
                return "active"
            if age_min < 15:
                return "idle"
            return "possibly dead"
        except ValueError:
            pass

    if last_task_update:
        try:
            ltu = datetime.datetime.fromisoformat(last_task_update)
            age_min = (now - ltu).total_seconds() / 60
            if age_min < 5:
                return "active"
            if age_min < 15:
                return "idle"
            return "possibly dead"
        except ValueError:
            pass

    return "possibly dead"


def party_status() -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.datetime.now()
    try:
        cursor.execute("SELECT * FROM agents ORDER BY last_seen DESC")
        agents = []

        for row in cursor.fetchall():
            a = enrich_agent_row(row, now)
            name = a["name"]

            cursor.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(activity_count), 0) as total_activity
                   FROM tasks
                   WHERE assigned_to = ? AND status IN ('open', 'assigned', 'in_progress')""",
                (name,),
            )
            task_row = cursor.fetchone()
            a["open_tasks"] = task_row["cnt"]
            a["total_activity"] = task_row["total_activity"]

            cursor.execute(
                "SELECT file_path, claimed_at FROM file_claims WHERE agent_name = ?",
                (name,),
            )
            claimed_files = []
            for claim in cursor.fetchall():
                fp = claim["file_path"]
                claimed_files.append({
                    "file_path": fp,
                    "claimed_at": claim["claimed_at"],
                    "mtime": _safe_mtime(fp),
                })
            a["claimed_files"] = claimed_files

            # Strip verbose fields for compact dashboard
            for key in ("context_summary", "files_read"):
                a.pop(key, None)

            agents.append(a)

        return {"agents": agents}
    finally:
        conn.close()


def check_activity(agent_name: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.datetime.now()
    try:
        cursor.execute("SELECT * FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"Agent '{agent_name}' not found."}

        result: dict[str, Any] = {
            "agent_name": agent_name,
            "agent_class": row["agent_class"],
            "status": row["status"],
            "last_seen": row["last_seen"],
            "current_zone": row["current_zone"],
        }

        if row["last_seen"]:
            try:
                ls = datetime.datetime.fromisoformat(row["last_seen"])
                result["last_seen_mins_ago"] = int((now - ls).total_seconds() // 60)
            except ValueError:
                pass

        cursor.execute(
            """SELECT id, title, status, updated_at, activity_count, zone
               FROM tasks
               WHERE assigned_to = ? AND status IN ('open', 'assigned', 'in_progress')
               ORDER BY updated_at DESC""",
            (agent_name,),
        )
        active_tasks = [dict(t) for t in cursor.fetchall()]
        result["active_tasks"] = active_tasks
        result["last_task_update"] = active_tasks[0]["updated_at"] if active_tasks else None

        claimed_files = []
        claimed_mtimes: list[str | None] = []
        cursor.execute(
            "SELECT file_path, claimed_at FROM file_claims WHERE agent_name = ?",
            (agent_name,),
        )
        for claim in cursor.fetchall():
            fp = claim["file_path"]
            mt = _safe_mtime(fp)
            claimed_files.append({"file_path": fp, "claimed_at": claim["claimed_at"], "mtime": mt})
            claimed_mtimes.append(mt)
        result["claimed_files"] = claimed_files

        zones: set[str] = set()
        for t in active_tasks:
            if t.get("zone"):
                zones.add(t["zone"])
        if row["current_zone"]:
            zones.add(row["current_zone"])
        result["zones"] = sorted(zones)

        zone_mtimes: list[str | None] = []
        for z in zones:
            if os.path.isdir(z):
                zone_mtimes.append(_safe_mtime(z))

        all_mtimes = claimed_mtimes + zone_mtimes
        result["judgment"] = _agent_judgment(row["last_seen"], result["last_task_update"], all_mtimes)

        return result
    finally:
        conn.close()


def check_freshness(agent_name: str, file_paths: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT context_updated_at FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"Agent '{agent_name}' not found."}

        context_updated_at = row["context_updated_at"]
        paths = [p.strip() for p in file_paths.split(",") if p.strip()]
        if not paths:
            return {"error": "No file paths provided."}

        if not context_updated_at:
            stale_files = []
            for fp in paths:
                stale_files.append({
                    "file_path": fp,
                    "mtime": _safe_mtime(fp),
                    "exists": os.path.exists(fp),
                    "stale": True,
                })
            return {
                "agent_name": agent_name,
                "context_updated_at": None,
                "note": "Agent has never called set-context — all files considered stale.",
                "files": stale_files,
                "stale_count": len([f for f in stale_files if f["exists"]]),
            }

        try:
            context_dt = datetime.datetime.fromisoformat(context_updated_at)
            context_ts = context_dt.timestamp()
        except ValueError:
            return {"error": f"Invalid context_updated_at timestamp for '{agent_name}'."}

        files_result = []
        stale_count = 0
        for fp in paths:
            entry: dict[str, Any] = {"file_path": fp, "exists": os.path.exists(fp)}
            if os.path.exists(fp):
                try:
                    file_mtime = os.path.getmtime(fp)
                    entry["mtime"] = datetime.datetime.fromtimestamp(file_mtime).isoformat()
                    entry["stale"] = file_mtime > context_ts
                    if entry["stale"]:
                        stale_count += 1
                except OSError:
                    entry["mtime"] = None
                    entry["stale"] = False
            else:
                entry["mtime"] = None
                entry["stale"] = False
            files_result.append(entry)

        result: dict[str, Any] = {
            "agent_name": agent_name,
            "context_updated_at": context_updated_at,
            "files": files_result,
            "stale_count": stale_count,
        }
        if stale_count > 0:
            result["warning"] = f"{stale_count} file(s) modified since last set-context."
        return result
    finally:
        conn.close()


def sitrep() -> dict[str, object]:
    """Fused COP: agents + tasks + zones + claims + flags + recent comms in one call."""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.datetime.now()
    try:
        # Agents with HP
        cursor.execute("SELECT * FROM agents ORDER BY last_seen DESC")
        agents = [enrich_agent_row(row, now) for row in cursor.fetchall()]

        # Active tasks
        cursor.execute(
            "SELECT * FROM tasks WHERE status IN ('open', 'assigned', 'in_progress') ORDER BY updated_at DESC"
        )
        active_tasks = [dict(row) for row in cursor.fetchall()]

        # File claims
        cursor.execute("SELECT * FROM file_claims ORDER BY agent_name")
        claims = [dict(row) for row in cursor.fetchall()]

        # Flags
        cursor.execute("SELECT * FROM flags")
        flags = {row["key"]: {"value": row["value"], "set_by": row["set_by"], "set_at": row["set_at"]} for row in cursor.fetchall()}

        # Active battle plan
        cursor.execute("SELECT * FROM battle_plan WHERE status = 'active' ORDER BY created_at DESC LIMIT 1")
        plan_row = cursor.fetchone()
        battle_plan = dict(plan_row) if plan_row else None
        if battle_plan:
            battle_plan["plan_content"] = read_content_file(battle_plan.get("plan_file"))

        # Recent comms (last 10)
        cursor.execute("SELECT from_agent, to_agent, timestamp, is_cc FROM messages ORDER BY timestamp DESC LIMIT 10")
        recent_comms = [dict(row) for row in cursor.fetchall()]

        return {
            "agents": agents,
            "active_tasks": active_tasks,
            "file_claims": claims,
            "flags": flags,
            "battle_plan": battle_plan,
            "recent_comms": recent_comms[::-1],
        }
    finally:
        conn.close()


def update_hp(
    agent_name: str,
    input_tokens: int,
    output_tokens: int,
    limit: int,
    turn_input: int | None = None,
    turn_output: int | None = None,
) -> dict[str, object]:
    """Daemon-only: write observed HP to SQLite."""
    conn = get_db()
    now = now_iso()
    try:
        conn.execute(
            """UPDATE agents SET
                hp_input_tokens = ?,
                hp_output_tokens = ?,
                hp_tokens_limit = ?,
                hp_turn_input = ?,
                hp_turn_output = ?,
                hp_updated_at = ?,
                last_seen = ?
               WHERE name = ?""",
            (input_tokens, output_tokens, limit, turn_input, turn_output, now, now, agent_name),
        )
        conn.commit()

        from minion_comms.db import hp_summary
        return {
            "status": "ok",
            "agent": agent_name,
            "hp": hp_summary(input_tokens, output_tokens, limit, turn_input, turn_output),
        }
    finally:
        conn.close()
