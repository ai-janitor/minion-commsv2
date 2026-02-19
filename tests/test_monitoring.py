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

    def test_update_hp_with_turn_values(self, isolated_db, coder_agent):
        """Per-turn values drive HP%; cumulative shown as session total."""
        result = update_hp(coder_agent, 246000, 700, 200000, turn_input=82000, turn_output=200)
        assert result["status"] == "ok"
        # HP% based on per-turn (82200/200000 = 41.1% used → 59% HP)
        assert "59%" in result["hp"]
        assert "session: 246k" in result["hp"]

    def test_update_hp_without_turn_values_backward_compat(self, isolated_db, coder_agent):
        """Without per-turn values, cumulative used for HP% (backward compat)."""
        result = update_hp(coder_agent, 50000, 10000, 200000)
        assert result["status"] == "ok"
        # 60000/200000 = 30% used → 70% HP
        assert "70%" in result["hp"]
        assert "session:" not in result["hp"]


class TestHpSummary:
    def test_hp_summary_per_turn(self):
        """Per-turn values used for HP% calculation."""
        from minion_comms.db import hp_summary
        s = hp_summary(246000, 700, 200000, turn_input=82000, turn_output=200)
        assert "59%" in s
        assert "82k/200k" in s
        assert "session: 246k" in s
        assert "Healthy" in s

    def test_hp_summary_cumulative_fallback(self):
        """Without per-turn, falls back to cumulative."""
        from minion_comms.db import hp_summary
        s = hp_summary(50000, 10000, 200000)
        assert "70%" in s
        assert "60k/200k" in s
        assert "session:" not in s

    def test_hp_summary_no_limit(self):
        from minion_comms.db import hp_summary
        assert hp_summary(50000, 10000, None) == "HP unknown"

    def test_hp_summary_zero_tokens(self):
        from minion_comms.db import hp_summary
        assert hp_summary(0, 0, 200000) == "HP unknown"
