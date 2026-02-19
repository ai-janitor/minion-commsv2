"""Tests for lifecycle: cold_start, fenix_down, debrief, end_session."""

import os
import tempfile

from minion_comms.comms import register
from minion_comms.lifecycle import cold_start, debrief, end_session, fenix_down
from minion_comms.warroom import set_battle_plan


class TestColdStart:
    def test_cold_start_not_registered(self, isolated_db):
        result = cold_start("ghost")
        assert "error" in result

    def test_cold_start_success(self, isolated_db, lead_agent, battle_plan):
        result = cold_start(lead_agent)
        assert result["agent_name"] == lead_agent
        assert result["battle_plan"] is not None
        assert "briefing_files" in result


class TestFenixDown:
    def test_fenix_down_success(self, isolated_db, coder_agent):
        result = fenix_down(coder_agent, "/tmp/notes.md,/tmp/findings.md", "halfway through auth")
        assert result["status"] == "recorded"
        assert result["files_count"] == 2

    def test_fenix_down_no_files(self, isolated_db, coder_agent):
        result = fenix_down(coder_agent, "")
        assert "error" in result

    def test_fenix_down_consumed_on_cold_start(self, isolated_db, lead_agent, battle_plan):
        fenix_down(lead_agent, "/tmp/notes.md")
        result = cold_start(lead_agent)
        assert len(result["fenix_down_records"]) == 1
        # Second cold_start should show consumed
        result2 = cold_start(lead_agent)
        assert len(result2["fenix_down_records"]) == 0


class TestDebrief:
    def test_debrief_lead_only(self, isolated_db, coder_agent):
        result = debrief(coder_agent, "/tmp/debrief.md")
        assert "error" in result

    def test_debrief_file_must_exist(self, isolated_db, lead_agent):
        result = debrief(lead_agent, "/nonexistent/debrief.md")
        assert "error" in result

    def test_debrief_success(self, isolated_db, lead_agent):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"Session debrief content")
            result = debrief(lead_agent, f.name)
        assert result["status"] == "filed"
        os.unlink(f.name)


class TestEndSession:
    def test_end_session_requires_debrief(self, isolated_db, lead_agent, battle_plan):
        result = end_session(lead_agent)
        assert "error" in result
        assert "debrief" in result["error"].lower()

    def test_end_session_success(self, isolated_db, lead_agent, battle_plan):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"debrief")
            debrief(lead_agent, f.name)
        result = end_session(lead_agent)
        assert result["status"] == "ended"
        os.unlink(f.name)
