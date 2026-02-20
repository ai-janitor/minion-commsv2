"""Tests for task system."""

import os
import tempfile

from minion_comms.comms import register
from minion_comms.tasks import (
    assign_task,
    close_task,
    create_task,
    get_task,
    get_tasks,
    submit_result,
    update_task,
)
from minion_comms.warroom import set_battle_plan


class TestCreateTask:
    def test_create_task_lead_only(self, isolated_db, coder_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"task spec")
            result = create_task(coder_agent, "fix bug", f.name)
        assert "error" in result
        os.unlink(f.name)

    def test_create_task_success(self, isolated_db, lead_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"task spec")
            result = create_task(lead_agent, "fix auth bug", f.name)
        assert result["status"] == "created"
        assert result["task_id"] == 1
        os.unlink(f.name)

    def test_create_task_no_battle_plan(self, isolated_db, lead_agent):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"task spec")
            result = create_task(lead_agent, "fix bug", f.name)
        assert "error" in result
        assert "battle plan" in result["error"]
        os.unlink(f.name)

    def test_create_task_missing_file(self, isolated_db, lead_agent, battle_plan):
        result = create_task(lead_agent, "fix bug", "/nonexistent/task.md")
        assert "error" in result


class TestAssignTask:
    def test_assign_task(self, isolated_db, lead_agent, coder_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            create_task(lead_agent, "task1", f.name)
        result = assign_task(lead_agent, 1, coder_agent)
        assert result["status"] == "assigned"
        os.unlink(f.name)


class TestUpdateTask:
    def test_update_task_increments_activity(self, isolated_db, lead_agent, coder_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            create_task(lead_agent, "task1", f.name)
        assign_task(lead_agent, 1, coder_agent)
        result = update_task(coder_agent, 1, status="in_progress")
        assert result["activity_count"] == 1
        result = update_task(coder_agent, 1, progress="halfway")
        assert result["activity_count"] == 2
        os.unlink(f.name)

    def test_update_task_warns_at_4(self, isolated_db, lead_agent, coder_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            create_task(lead_agent, "task1", f.name)
        assign_task(lead_agent, 1, coder_agent)
        for _ in range(4):
            result = update_task(coder_agent, 1, progress="trying again")
        assert "warning" in result
        os.unlink(f.name)

    def test_cannot_close_via_update(self, isolated_db, lead_agent, coder_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            create_task(lead_agent, "task1", f.name)
        result = update_task(coder_agent, 1, status="closed")
        assert "error" in result
        os.unlink(f.name)


class TestTransitionWarnings:
    def _make_task(self, lead, coder):
        """Helper: create + assign a task, return task_id."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            create_task(lead, "task1", f.name)
        assign_task(lead, 1, coder)
        self._tmpfiles = getattr(self, "_tmpfiles", [])
        self._tmpfiles.append(f.name)
        return 1

    def test_skip_in_progress_warns(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """assigned → fixed skips in_progress — should warn."""
        self._make_task(lead_agent, coder_agent)
        result = update_task(coder_agent, 1, status="fixed")
        assert "transition_warning" in result
        assert "Skipped steps" in result["transition_warning"]
        for f in self._tmpfiles:
            os.unlink(f)

    def test_valid_transition_no_warning(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """assigned → in_progress is valid — no transition_warning."""
        self._make_task(lead_agent, coder_agent)
        result = update_task(coder_agent, 1, status="in_progress")
        assert "transition_warning" not in result
        for f in self._tmpfiles:
            os.unlink(f)

    def test_ownership_warning(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """Agent B updates agent A's task — should warn about ownership."""
        self._make_task(lead_agent, coder_agent)
        register("other1", "coder")
        result = update_task("other1", 1, status="in_progress")
        assert "transition_warning" in result
        assert "Ownership" in result["transition_warning"]
        for f in self._tmpfiles:
            os.unlink(f)

    def test_fixed_without_result_warns(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """Setting fixed without submit_result — should warn."""
        self._make_task(lead_agent, coder_agent)
        update_task(coder_agent, 1, status="in_progress")
        result = update_task(coder_agent, 1, status="fixed")
        assert "transition_warning" in result
        assert "submit_result" in result["transition_warning"]
        for f in self._tmpfiles:
            os.unlink(f)

    def test_fixed_with_result_no_result_warning(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """Setting fixed after submit_result — no result warning."""
        self._make_task(lead_agent, coder_agent)
        update_task(coder_agent, 1, status="in_progress")
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as rf:
            rf.write(b"result")
            self._tmpfiles.append(rf.name)
            submit_result(coder_agent, 1, rf.name)
        result = update_task(coder_agent, 1, status="fixed")
        assert "transition_warning" not in result or "submit_result" not in result.get("transition_warning", "")
        for f in self._tmpfiles:
            os.unlink(f)


class TestCloseTask:
    def test_close_task_requires_result(self, isolated_db, lead_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            create_task(lead_agent, "task1", f.name)
        result = close_task(lead_agent, 1)
        assert "error" in result
        assert "result file" in result["error"]
        os.unlink(f.name)

    def test_close_task_success(self, isolated_db, lead_agent, coder_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
            tf.write(b"spec")
            create_task(lead_agent, "task1", tf.name)
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as rf:
            rf.write(b"result")
            submit_result(coder_agent, 1, rf.name)
        result = close_task(lead_agent, 1)
        assert result["status"] == "closed"
        os.unlink(tf.name)
        os.unlink(rf.name)


class TestGetTasks:
    def test_get_tasks_default(self, isolated_db, lead_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            create_task(lead_agent, "task1", f.name)
        result = get_tasks()
        assert len(result["tasks"]) == 1
        os.unlink(f.name)

    def test_get_task_by_id(self, isolated_db, lead_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"spec")
            create_task(lead_agent, "task1", f.name)
        result = get_task(1)
        assert result["task"]["title"] == "task1"
        os.unlink(f.name)
