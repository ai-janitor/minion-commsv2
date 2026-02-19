"""File Safety — claim, release, get_claims."""

from __future__ import annotations

import json
import os
from typing import Any

from minion_comms.db import get_db, now_iso


def claim_file(agent_name: str, file_path: str) -> dict[str, object]:
    normalized = os.path.abspath(file_path)
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (agent_name,))
        if not cursor.fetchone():
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}

        cursor.execute(
            "SELECT agent_name, claimed_at FROM file_claims WHERE file_path = ?",
            (normalized,),
        )
        existing = cursor.fetchone()

        if existing:
            if existing["agent_name"] == agent_name:
                return {"status": "already_claimed", "file": normalized, "by": agent_name}

            cursor.execute(
                "INSERT OR IGNORE INTO file_waitlist (file_path, agent_name, added_at) VALUES (?, ?, ?)",
                (normalized, agent_name, now),
            )
            conn.commit()
            return {
                "error": f"BLOCKED: File '{normalized}' claimed by '{existing['agent_name']}' since {existing['claimed_at']}. Added to waitlist.",
            }

        cursor.execute(
            "INSERT INTO file_claims (file_path, agent_name, claimed_at) VALUES (?, ?, ?)",
            (normalized, agent_name, now),
        )
        cursor.execute("UPDATE agents SET last_seen = ? WHERE name = ?", (now, agent_name))
        conn.commit()

        return {"status": "claimed", "file": normalized, "by": agent_name}
    finally:
        conn.close()


def release_file(agent_name: str, file_path: str, force: bool = False) -> dict[str, object]:
    normalized = os.path.abspath(file_path)
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name, agent_class FROM agents WHERE name = ?", (agent_name,))
        agent_row = cursor.fetchone()
        if not agent_row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}

        cursor.execute("SELECT agent_name FROM file_claims WHERE file_path = ?", (normalized,))
        claim = cursor.fetchone()
        if not claim:
            return {"error": f"File '{normalized}' is not claimed by anyone."}

        claim_holder = claim["agent_name"]
        if claim_holder != agent_name:
            if agent_row["agent_class"] != "lead" or not force:
                return {"error": f"BLOCKED: File '{normalized}' is claimed by '{claim_holder}'. Only holder or lead (with --force) can release."}

        cursor.execute("DELETE FROM file_claims WHERE file_path = ?", (normalized,))
        cursor.execute(
            "SELECT agent_name FROM file_waitlist WHERE file_path = ? ORDER BY added_at ASC",
            (normalized,),
        )
        waiters = [row["agent_name"] for row in cursor.fetchall()]
        cursor.execute("DELETE FROM file_waitlist WHERE file_path = ?", (normalized,))
        cursor.execute("UPDATE agents SET last_seen = ? WHERE name = ?", (now, agent_name))
        conn.commit()

        result: dict[str, object] = {"status": "released", "file": normalized, "was_held_by": claim_holder}
        if claim_holder != agent_name:
            result["force_released_by"] = agent_name
        if waiters:
            result["waitlisted_agents"] = waiters
        return result
    finally:
        conn.close()


def get_claims(agent_name: str = "") -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        if agent_name:
            cursor.execute(
                "SELECT * FROM file_claims WHERE agent_name = ? ORDER BY claimed_at DESC",
                (agent_name,),
            )
        else:
            cursor.execute("SELECT * FROM file_claims ORDER BY agent_name, claimed_at DESC")
        claims = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT file_path, agent_name, added_at FROM file_waitlist ORDER BY added_at ASC")
        waitlist = [dict(row) for row in cursor.fetchall()]

        return {"claims": claims, "waitlist": waitlist}
    finally:
        conn.close()
