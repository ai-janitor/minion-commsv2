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
