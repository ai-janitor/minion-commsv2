"""Tests for war room: battle plans and raid log."""

from minion_comms.comms import register
from minion_comms.warroom import (
    get_battle_plan,
    get_raid_log,
    log_raid,
    set_battle_plan,
    update_battle_plan_status,
)


class TestBattlePlan:
    def test_set_battle_plan_lead_only(self, isolated_db):
        register("coder1", "coder")
        result = set_battle_plan("coder1", "my plan")
        assert "error" in result

    def test_set_battle_plan_success(self, isolated_db, lead_agent):
        result = set_battle_plan(lead_agent, "Attack the auth module")
        assert result["status"] == "active"
        assert result["plan_id"] == 1

    def test_set_battle_plan_supersedes_old(self, isolated_db, lead_agent):
        set_battle_plan(lead_agent, "plan 1")
        set_battle_plan(lead_agent, "plan 2")
        old = get_battle_plan("superseded")
        assert len(old["plans"]) == 1
        active = get_battle_plan("active")
        assert len(active["plans"]) == 1

    def test_get_battle_plan_with_content(self, isolated_db, lead_agent):
        set_battle_plan(lead_agent, "The plan content here")
        result = get_battle_plan("active")
        assert result["plans"][0]["plan_content"] == "The plan content here"

    def test_update_battle_plan_status(self, isolated_db, lead_agent):
        set_battle_plan(lead_agent, "plan")
        result = update_battle_plan_status(lead_agent, 1, "completed")
        assert result["status"] == "updated"
        assert result["new_status"] == "completed"


class TestRaidLog:
    def test_log_raid(self, isolated_db, lead_agent):
        result = log_raid(lead_agent, "Found a bug in auth", "high")
        assert result["status"] == "logged"

    def test_log_raid_invalid_priority(self, isolated_db, lead_agent):
        result = log_raid(lead_agent, "entry", "super-critical")
        assert "error" in result

    def test_get_raid_log_with_content(self, isolated_db, lead_agent):
        log_raid(lead_agent, "Entry content here", "normal")
        result = get_raid_log()
        assert len(result["entries"]) == 1
        assert result["entries"][0]["entry_content"] == "Entry content here"

    def test_get_raid_log_filter_priority(self, isolated_db, lead_agent):
        log_raid(lead_agent, "low entry", "low")
        log_raid(lead_agent, "high entry", "high")
        result = get_raid_log(priority="high")
        assert len(result["entries"]) == 1
        assert result["entries"][0]["priority"] == "high"
