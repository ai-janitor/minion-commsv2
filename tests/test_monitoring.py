"""Tests for monitoring: party_status, check_activity, check_freshness, sitrep, update_hp."""

from minion_comms.comms import register, set_context
from minion_comms.monitoring import (
    check_activity,
    check_freshness,
    party_status,
    sitrep,
    update_hp,
)


class TestPartyStatus:
    def test_party_status_empty(self, isolated_db):
        result = party_status()
        assert result["agents"] == []

    def test_party_status_with_agents(self, isolated_db, lead_agent, coder_agent):
        result = party_status()
        assert len(result["agents"]) == 2


class TestCheckActivity:
    def test_check_activity_not_found(self, isolated_db):
        result = check_activity("ghost")
        assert "error" in result

    def test_check_activity_success(self, isolated_db, coder_agent):
        result = check_activity(coder_agent)
        assert result["agent_name"] == coder_agent
        assert "judgment" in result


class TestCheckFreshness:
    def test_check_freshness_no_context(self, isolated_db, coder_agent):
        result = check_freshness(coder_agent, "/tmp/test.py")
        assert result["note"] is not None  # All files considered stale

    def test_check_freshness_with_context(self, isolated_db, coder_agent, tmp_path):
        set_context(coder_agent, "loaded")
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")
        result = check_freshness(coder_agent, str(test_file))
        assert "files" in result


class TestSitrep:
    def test_sitrep_returns_all_sections(self, isolated_db, lead_agent):
        result = sitrep()
        assert "agents" in result
        assert "active_tasks" in result
        assert "file_claims" in result
        assert "flags" in result
        assert "recent_comms" in result


class TestUpdateHP:
    def test_update_hp(self, isolated_db, coder_agent):
        result = update_hp(coder_agent, 50000, 10000, 200000)
        assert result["status"] == "ok"
        assert "HP" in result["hp"]
