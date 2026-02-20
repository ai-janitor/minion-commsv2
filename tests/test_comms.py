"""Tests for core comms: register, deregister, rename, set_status,
set_context, who, send, check_inbox, get_history, purge_inbox."""

import os

from minion_comms.comms import (
    check_inbox,
    deregister,
    get_history,
    purge_inbox,
    register,
    rename,
    send,
    set_context,
    set_status,
    who,
)


class TestRegister:
    def test_register_success(self, isolated_db):
        result = register("agent1", "coder")
        assert result["status"] == "registered"
        assert result["agent"] == "agent1"
        assert result["class"] == "coder"

    def test_register_invalid_class(self, isolated_db):
        result = register("agent1", "wizard")
        assert "error" in result

    def test_register_invalid_transport(self, isolated_db):
        result = register("agent1", "coder", transport="pigeon")
        assert "error" in result

    def test_register_model_whitelist_blocks(self, isolated_db):
        result = register("agent1", "coder", model="gpt-4")
        assert "error" in result
        assert "not allowed" in result["error"]

    def test_register_model_whitelist_allows(self, isolated_db):
        result = register("agent1", "coder", model="claude-sonnet-4-6")
        assert result["status"] == "registered"

    def test_register_oracle_any_model(self, isolated_db):
        result = register("agent1", "oracle", model="llama-3")
        assert result["status"] == "registered"

    def test_re_register_updates(self, isolated_db):
        register("agent1", "coder", description="first")
        result = register("agent1", "oracle", description="second")
        assert result["status"] == "registered"
        assert result["class"] == "oracle"


class TestDeregister:
    def test_deregister_success(self, isolated_db):
        register("agent1", "coder")
        result = deregister("agent1")
        assert result["status"] == "deregistered"

    def test_deregister_not_found(self, isolated_db):
        result = deregister("ghost")
        assert "error" in result

    def test_deregister_releases_claims(self, isolated_db):
        register("agent1", "coder")
        from minion_comms.filesafety import claim_file
        claim_file("agent1", "/tmp/test.py")
        result = deregister("agent1")
        assert result["released_claims"] == 1


class TestRename:
    def test_rename_success(self, isolated_db):
        register("old", "coder")
        result = rename("old", "new")
        assert result["status"] == "renamed"
        # Verify old name is gone
        agents = who()["agents"]
        names = [a["name"] for a in agents]
        assert "new" in names
        assert "old" not in names

    def test_rename_not_found(self, isolated_db):
        result = rename("ghost", "new")
        assert "error" in result

    def test_rename_conflict(self, isolated_db):
        register("a", "coder")
        register("b", "coder")
        result = rename("a", "b")
        assert "error" in result


class TestSetStatus:
    def test_set_status(self, isolated_db):
        register("agent1", "coder")
        result = set_status("agent1", "working on BUG-001")
        assert result["status"] == "ok"
        assert result["new_status"] == "working on BUG-001"


class TestSetContext:
    def test_set_context(self, isolated_db):
        register("agent1", "coder")
        result = set_context("agent1", "auth module loaded", 50000, 200000)
        assert result["status"] == "ok"
        assert "hp" in result


class TestWho:
    def test_who_empty(self, isolated_db):
        result = who()
        assert result["agents"] == []

    def test_who_lists_agents(self, isolated_db):
        register("a", "lead")
        register("b", "coder")
        result = who()
        assert len(result["agents"]) == 2


class TestSend:
    def test_send_blocked_no_battle_plan(self, isolated_db):
        register("sender", "coder")
        set_context("sender", "loaded")
        result = send("sender", "receiver", "hello")
        assert "error" in result
        assert "battle plan" in result["error"]

    def test_send_blocked_unread_messages(self, isolated_db, battle_plan, coder_agent):
        set_context(coder_agent, "loaded")
        set_context("lead", "coordinating")
        # Send a message from lead to coder so coder has unread
        first = send("lead", coder_agent, "read this first")
        assert first["status"] == "sent"
        # Now coder tries to send without reading
        result = send(coder_agent, "lead", "reply")
        assert "error" in result
        assert "unread" in result["error"]

    def test_send_success(self, isolated_db, battle_plan, coder_agent):
        set_context(coder_agent, "loaded")
        result = send(coder_agent, coder_agent, "hello self")
        assert result["status"] == "sent"
        # Auto-CC to lead
        assert "lead" in result.get("cc", [])

    def test_send_trigger_detection(self, isolated_db, battle_plan, coder_agent):
        set_context(coder_agent, "loaded")
        result = send(coder_agent, coder_agent, "we need moon_crash NOW")
        assert "moon_crash" in result.get("triggers", [])

    def test_send_writes_content_file(self, isolated_db, battle_plan, coder_agent):
        set_context(coder_agent, "loaded")
        send(coder_agent, coder_agent, "test content body")
        inbox = check_inbox(coder_agent)
        msg = inbox["messages"][0]
        assert msg["content"] == "test content body"
        assert os.path.exists(msg["content_file"])

    def test_send_artifact_nudge_fires_for_large_inline_message(self, isolated_db, battle_plan, coder_agent):
        # Large message with no file path reference should trigger artifact_reminder
        set_context(coder_agent, "loaded")
        long_inline = "This is a detailed spec review. " * 20  # >500 chars, no .md path
        result = send(coder_agent, coder_agent, long_inline)
        assert "artifact_reminder" in result
        check_inbox(coder_agent)  # clear inbox for next test

    def test_send_artifact_nudge_skipped_for_short_message(self, isolated_db, battle_plan, coder_agent):
        set_context(coder_agent, "loaded")
        result = send(coder_agent, coder_agent, "short message")
        assert "artifact_reminder" not in result
        check_inbox(coder_agent)

    def test_send_artifact_nudge_skipped_when_file_path_present(self, isolated_db, battle_plan, coder_agent):
        # Large message referencing a .md file should NOT trigger nudge
        set_context(coder_agent, "loaded")
        long_with_path = ("Review complete. See .dead-drop/ui-dashboard/spec-review.md for details. " * 10)
        result = send(coder_agent, coder_agent, long_with_path)
        assert "artifact_reminder" not in result
        check_inbox(coder_agent)


class TestTaskNudge:
    """BUG-002: send() nudges lead when target agent has no open task."""

    def _make_task_file(self, tmp_path):
        f = tmp_path / "task.md"
        f.write_text("# task")
        return str(f)

    def test_nudge_fires_when_lead_sends_with_no_task(self, isolated_db, battle_plan, coder_agent):
        # Lead sends to coder with no task assigned → nudge in response
        set_context("lead", "loaded")
        result = send("lead", coder_agent, "work on this feature")
        assert "nudge" in result
        assert coder_agent in result["nudge"]

    def test_nudge_absent_when_assigned_task_exists(self, isolated_db, battle_plan, coder_agent, tmp_path):
        from minion_comms.tasks import assign_task, create_task
        task_file = self._make_task_file(tmp_path)
        ct = create_task("lead", "Fix the thing", task_file)
        assign_task("lead", ct["task_id"], coder_agent)
        set_context("lead", "loaded")
        result = send("lead", coder_agent, "here is your task")
        assert "nudge" not in result

    def test_nudge_absent_for_non_lead_sender(self, isolated_db, battle_plan, coder_agent):
        # Coder → coder: no nudge regardless of tasks
        from minion_comms.comms import register
        register("coder2", "coder")
        set_context(coder_agent, "loaded")
        result = send(coder_agent, "coder2", "hello")
        assert "nudge" not in result

    def test_nudge_absent_when_send_to_all(self, isolated_db, battle_plan):
        # Lead broadcasts to "all" — nudge logic skipped
        set_context("lead", "loaded")
        result = send("lead", "all", "standup time")
        assert "nudge" not in result


class TestCheckInbox:
    def test_empty_inbox(self, isolated_db, coder_agent):
        result = check_inbox(coder_agent)
        assert result["messages"] == []

    def test_inbox_with_messages(self, isolated_db, battle_plan, coder_agent):
        set_context(coder_agent, "loaded")
        send(coder_agent, coder_agent, "msg1")
        result = check_inbox(coder_agent)
        assert len(result["messages"]) == 1
        assert result["messages"][0]["content"] == "msg1"

    def test_inbox_marks_read(self, isolated_db, battle_plan, coder_agent):
        set_context(coder_agent, "loaded")
        send(coder_agent, coder_agent, "msg1")
        check_inbox(coder_agent)
        # Second check should be empty
        result = check_inbox(coder_agent)
        assert result["messages"] == []


class TestGetHistory:
    def test_get_history(self, isolated_db, battle_plan, coder_agent):
        set_context(coder_agent, "loaded")
        send(coder_agent, coder_agent, "msg1")
        check_inbox(coder_agent)
        result = get_history(10)
        assert len(result["messages"]) >= 1


class TestPurgeInbox:
    def test_purge_inbox(self, isolated_db, coder_agent):
        result = purge_inbox(coder_agent, 0)
        assert result["status"] == "purged"
