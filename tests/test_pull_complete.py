"""Tests for pull_task and complete_task."""

import os
import tempfile

from minion_comms.comms import register
from minion_comms.tasks import (
    assign_task,
    complete_task,
    create_task,
    get_task,
    pull_task,
    update_task,
)
from minion_comms.warroom import set_battle_plan


class TestPullTask:
    def _setup_task(self, lead, class_required="coder"):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"task spec content")
            self._tmpfiles = getattr(self, "_tmpfiles", [])
            self._tmpfiles.append(f.name)
            result = create_task(lead, "test task", f.name, class_required=class_required)
            return result

    def teardown_method(self):
        for f in getattr(self, "_tmpfiles", []):
            if os.path.exists(f):
                os.unlink(f)

    def test_pull_nonexistent_task(self, isolated_db, lead_agent, coder_agent, battle_plan):
        result = pull_task(coder_agent, 999)
        assert "error" in result

    def test_pull_claim_by_id(self, isolated_db, lead_agent, coder_agent, battle_plan):
        self._setup_task(lead_agent, class_required="coder")
        result = pull_task(coder_agent, 1)
        assert result["status"] == "claimed"
        assert result["task_id"] == 1
        assert "task_content" in result

        # Task should now be assigned
        task = get_task(1)
        assert task["task"]["assigned_to"] == coder_agent
        assert task["task"]["status"] == "assigned"

    def test_pull_already_assigned(self, isolated_db, lead_agent, coder_agent, battle_plan):
        self._setup_task(lead_agent, class_required="coder")
        assign_task(lead_agent, 1, coder_agent)
        # Re-pulling own assigned task should work
        result = pull_task(coder_agent, 1)
        assert result["status"] == "claimed"

    def test_pull_blocked_task(self, isolated_db, lead_agent, coder_agent, battle_plan):
        self._setup_task(lead_agent, class_required="coder")
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"blocked task")
            self._tmpfiles.append(f.name)
            create_task(lead_agent, "blocked task", f.name, blocked_by="1", class_required="coder")

        result = pull_task(coder_agent, 2)
        assert "error" in result
        assert "blocker" in result["error"]

    def test_pull_not_registered(self, isolated_db):
        result = pull_task("ghost", 1)
        assert "error" in result

    def test_pull_moon_crash(self, isolated_db, lead_agent, coder_agent, battle_plan):
        from minion_comms.db import get_db, now_iso
        conn = get_db()
        conn.execute("INSERT INTO flags (key, value, set_by, set_at) VALUES ('moon_crash', '1', 'lead', ?)", (now_iso(),))
        conn.commit()
        conn.close()

        self._setup_task(lead_agent, class_required="coder")
        result = pull_task(coder_agent, 1)
        assert "error" in result
        assert "moon_crash" in result["error"]

    def test_pull_terminal_task(self, isolated_db, lead_agent, coder_agent, battle_plan):
        self._setup_task(lead_agent, class_required="coder")
        from minion_comms.db import get_db
        conn = get_db()
        conn.execute("UPDATE tasks SET status = 'closed' WHERE id = 1")
        conn.commit()
        conn.close()

        result = pull_task(coder_agent, 1)
        assert "error" in result
        assert "terminal" in result["error"]

    def test_pull_race_guard(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """Second pull for same task should lose the race."""
        self._setup_task(lead_agent, class_required="coder")
        register("coder2", "coder")

        r1 = pull_task(coder_agent, 1)
        assert r1["status"] == "claimed"

        r2 = pull_task("coder2", 1)
        assert "error" in r2
        assert "Race" in r2["error"] or "claimed" in r2.get("error", "")

    def test_pull_review_pipeline(self, isolated_db, lead_agent, battle_plan):
        """Oracle can claim fixed tasks via complete-task handoff."""
        register("oracle1", "oracle")
        self._setup_task(lead_agent, class_required="coder")
        register("coder1", "coder")
        assign_task(lead_agent, 1, "coder1")
        update_task("coder1", 1, status="in_progress")
        # complete_task clears assigned_to for handoff stages
        complete_task("coder1", 1, passed=True)

        result = pull_task("oracle1", 1)
        assert result["status"] == "claimed"


class TestCompleteTask:
    def _setup_assigned_task(self, lead, coder):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            self._tmpfiles = getattr(self, "_tmpfiles", [])
            self._tmpfiles.append(f.name)
            create_task(lead, "test task", f.name, class_required="coder")
        assign_task(lead, 1, coder)
        update_task(coder, 1, status="in_progress")

    def teardown_method(self):
        for f in getattr(self, "_tmpfiles", []):
            if os.path.exists(f):
                os.unlink(f)

    def test_complete_advances_status(self, isolated_db, lead_agent, coder_agent, battle_plan):
        self._setup_assigned_task(lead_agent, coder_agent)
        result = complete_task(coder_agent, 1)
        assert result["status"] == "completed"
        assert result["from_status"] == "in_progress"
        assert result["to_status"] == "fixed"

        task = get_task(1)
        assert task["task"]["status"] == "fixed"

    def test_complete_failed_routes_back(self, isolated_db, lead_agent, coder_agent, battle_plan):
        self._setup_assigned_task(lead_agent, coder_agent)
        complete_task(coder_agent, 1, passed=True)

        result = complete_task(coder_agent, 1, passed=False)
        assert result["to_status"] == "assigned"

    def test_complete_terminal_blocked(self, isolated_db, lead_agent, coder_agent, battle_plan):
        self._setup_assigned_task(lead_agent, coder_agent)
        from minion_comms.db import get_db
        conn = get_db()
        conn.execute("UPDATE tasks SET status = 'closed' WHERE id = 1")
        conn.commit()
        conn.close()

        result = complete_task(coder_agent, 1)
        assert "error" in result
        assert "terminal" in result["error"]

    def test_complete_not_registered(self, isolated_db):
        result = complete_task("ghost", 1)
        assert "error" in result

    def test_complete_nonexistent_task(self, isolated_db, lead_agent, coder_agent, battle_plan):
        result = complete_task(coder_agent, 999)
        assert "error" in result

    def test_complete_eligible_classes_returned(self, isolated_db, lead_agent, coder_agent, battle_plan):
        self._setup_assigned_task(lead_agent, coder_agent)
        result = complete_task(coder_agent, 1)
        assert "eligible_classes" in result
