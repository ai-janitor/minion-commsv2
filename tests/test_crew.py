"""Tests for crew + triggers: hand_off_zone, get_triggers, clear_moon_crash."""

from minion_comms.comms import register, send, set_context, check_inbox
from minion_comms.crew import hand_off_zone
from minion_comms.triggers import clear_moon_crash, get_triggers
from minion_comms.warroom import set_battle_plan


class TestGetTriggers:
    def test_get_triggers(self, isolated_db):
        result = get_triggers()
        assert "triggers" in result
        assert "moon_crash" in result["triggers"]
        assert "fenix_down" in result["triggers"]


class TestClearMoonCrash:
    def test_clear_when_not_active(self, isolated_db, lead_agent):
        result = clear_moon_crash(lead_agent)
        assert result["status"] == "noop"

    def test_clear_moon_crash_flow(self, isolated_db, lead_agent, coder_agent, battle_plan):
        set_context(coder_agent, "loaded")
        # Trigger moon_crash via send
        send(coder_agent, lead_agent, "moon_crash emergency!")
        check_inbox(lead_agent)
        # Clear it
        result = clear_moon_crash(lead_agent)
        assert result["status"] == "cleared"

    def test_clear_moon_crash_lead_only(self, isolated_db, coder_agent):
        result = clear_moon_crash(coder_agent)
        assert "error" in result


class TestHandOffZone:
    def test_hand_off_zone_success(self, isolated_db):
        register("oracle1", "oracle")
        register("oracle2", "oracle")
        register("oracle3", "oracle")
        result = hand_off_zone("oracle1", "oracle2,oracle3", "src/auth/")
        assert result["status"] == "handed_off"
        assert result["zone"] == "src/auth/"
        assert len(result["to"]) == 2

    def test_hand_off_zone_missing_agent(self, isolated_db):
        register("oracle1", "oracle")
        result = hand_off_zone("oracle1", "ghost", "src/auth/")
        assert "error" in result
