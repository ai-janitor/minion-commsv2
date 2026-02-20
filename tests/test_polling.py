"""Tests for polling loop — messages, tasks, signals, timeout."""

import os
import tempfile

from minion_comms.db import get_db, now_iso
from minion_comms.polling import poll_loop
from minion_comms.tasks import create_task
from minion_comms.warroom import set_battle_plan


class TestPollLoop:
    def test_timeout_returns_exit_1(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """Empty inbox + no tasks → timeout."""
        result = poll_loop(coder_agent, interval=1, timeout=2)
        assert result["exit_code"] == 1

    def test_unread_message_returns_content(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """Unread message → delivers message content."""
        conn = get_db()
        conn.execute(
            "INSERT INTO messages (from_agent, to_agent, content_file, timestamp, read_flag) VALUES ('lead', ?, '/tmp/test.md', ?, 0)",
            (coder_agent, now_iso()),
        )
        conn.commit()
        conn.close()

        result = poll_loop(coder_agent, interval=1, timeout=5)
        assert result["exit_code"] == 0
        assert "messages" in result
        assert len(result["messages"]) > 0

    def test_stand_down_returns_signal(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """stand_down flag → exit code 3 with signal name."""
        conn = get_db()
        conn.execute("INSERT INTO flags (key, value, set_by, set_at) VALUES ('stand_down', '1', 'lead', ?)", (now_iso(),))
        conn.commit()
        conn.close()

        result = poll_loop(coder_agent, interval=1, timeout=5)
        assert result["exit_code"] == 3
        assert result["signal"] == "stand_down"

    def test_retire_returns_signal(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """retire flag → exit code 3."""
        conn = get_db()
        conn.execute("INSERT INTO agent_retire (agent_name, set_at, set_by) VALUES (?, ?, 'lead')", (coder_agent, now_iso()))
        conn.commit()
        conn.close()

        result = poll_loop(coder_agent, interval=1, timeout=5)
        assert result["exit_code"] == 3
        assert result["signal"] == "retire"

    def test_available_task_returned(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """Available task → listed with claim command."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"task spec")
            create_task(lead_agent, "auto task", f.name, class_required="coder")

        result = poll_loop(coder_agent, interval=1, timeout=5)
        assert result["exit_code"] == 0
        assert "tasks" in result
        assert len(result["tasks"]) > 0
        assert result["tasks"][0]["task_id"] == 1
        assert "claim_cmd" in result["tasks"][0]
        os.unlink(f.name)

    def test_terminal_transport_gets_hint(self, isolated_db, lead_agent, coder_agent, battle_plan):
        """Terminal agents get restart reminder."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"task spec")
            create_task(lead_agent, "test", f.name, class_required="coder")

        result = poll_loop(coder_agent, interval=1, timeout=5)
        assert result["exit_code"] == 0
        assert "transport_hint" in result
        os.unlink(f.name)

    def test_daemon_transport_no_hint(self, isolated_db, lead_agent, battle_plan):
        """Daemon agents don't get restart reminder."""
        from minion_comms.comms import register
        register("daemon1", "coder", transport="daemon")

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"task spec")
            create_task(lead_agent, "test", f.name, class_required="coder")

        result = poll_loop("daemon1", interval=1, timeout=5)
        assert result["exit_code"] == 0
        assert "transport_hint" not in result
        os.unlink(f.name)
