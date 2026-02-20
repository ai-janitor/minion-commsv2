"""Tests for monitoring: party_status, check_activity, check_freshness, sitrep, update_hp."""

import json

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
        """Per-turn input drives HP% (input only, not output)."""
        result = update_hp(coder_agent, 246000, 700, 200000, turn_input=82000, turn_output=200)
        assert result["status"] == "ok"
        # HP% based on per-turn input only: 82000/200000 = 41% used → 59% HP
        assert "59%" in result["hp"]
        assert "82k/200k" in result["hp"]

    def test_update_hp_without_turn_values_backward_compat(self, isolated_db, coder_agent):
        """Without per-turn values, cumulative input capped at limit for HP%."""
        result = update_hp(coder_agent, 50000, 10000, 200000)
        assert result["status"] == "ok"
        # Input only: 50000/200000 = 25% used → 75% HP
        assert "75%" in result["hp"]
        assert "50k/200k" in result["hp"]


class TestHpSummary:
    def test_hp_summary_per_turn(self):
        """Per-turn input used for HP% (input only)."""
        from minion_comms.db import hp_summary
        s = hp_summary(246000, 700, 200000, turn_input=82000, turn_output=200)
        assert "59%" in s
        assert "82k/200k" in s
        assert "Healthy" in s

    def test_hp_summary_cumulative_fallback(self):
        """Without per-turn, falls back to cumulative input capped at limit."""
        from minion_comms.db import hp_summary
        s = hp_summary(50000, 10000, 200000)
        assert "75%" in s
        assert "50k/200k" in s

    def test_hp_summary_cumulative_exceeds_limit(self):
        """Cumulative > limit (post-compaction) gets capped — display stays in range."""
        from minion_comms.db import hp_summary
        s = hp_summary(13316463, 500000, 200000)
        # Capped: min(13316463, 200000) = 200000 → 0% HP [200k/200k]
        assert "0%" in s
        assert "200k/200k" in s
        assert "CRITICAL" in s

    def test_hp_summary_no_limit(self):
        from minion_comms.db import hp_summary
        assert hp_summary(50000, 10000, None) == "HP unknown"

    def test_hp_summary_zero_tokens(self):
        from minion_comms.db import hp_summary
        assert hp_summary(0, 0, 200000) == "HP unknown"


class TestSelfReportedHP:
    """Verify set-context --hp self-reporting path and daemon gate."""

    def _get_hp_cols(self, agent_name: str) -> dict:
        from minion_comms.db import get_db
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT hp_turn_input, hp_tokens_limit FROM agents WHERE name = ?",
                (agent_name,),
            )
            row = cursor.fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def test_set_context_hp_writes_db(self, isolated_db, coder_agent):
        """set_context(hp=75) → DB has hp_turn_input=25, hp_tokens_limit=100."""
        from minion_comms.comms import set_context
        set_context(coder_agent, "working", hp=75)
        cols = self._get_hp_cols(coder_agent)
        assert cols["hp_turn_input"] == 25
        assert cols["hp_tokens_limit"] == 100

    def test_hp_summary_from_self_reported(self):
        """hp_summary with sentinel values (limit=100, turn_input=25) → 75% HP."""
        from minion_comms.db import hp_summary
        s = hp_summary(None, None, 100, turn_input=25)
        assert "75%" in s
        assert "Healthy" in s

    def test_update_hp_gated_when_self_reported(self, isolated_db, coder_agent):
        """After set_context(hp=75), daemon update_hp() does NOT overwrite DB."""
        from minion_comms.comms import set_context
        set_context(coder_agent, "working", hp=75)
        # Daemon fires with large real token counts
        update_hp(coder_agent, 150000, 5000, 200000, turn_input=150000)
        # Self-reported sentinel values must remain intact
        cols = self._get_hp_cols(coder_agent)
        assert cols["hp_tokens_limit"] == 100
        assert cols["hp_turn_input"] == 25

    def test_update_hp_not_gated_without_self_reported(self, isolated_db, coder_agent):
        """Normal agent (no set_context --hp): update_hp() writes daemon values."""
        update_hp(coder_agent, 50000, 10000, 200000)
        cols = self._get_hp_cols(coder_agent)
        assert cols["hp_tokens_limit"] == 200000

    def test_cli_set_context_hp_flag(self, isolated_db, coder_agent):
        """set_context with hp=80 returns hp key with correct percentage in result."""
        from minion_comms.comms import set_context
        result = set_context(coder_agent, "working", hp=80)
        assert "hp" in result
        assert "80%" in result["hp"]

    def test_set_context_hp_100_no_hp_unknown(self, isolated_db, coder_agent):
        """hp=100 uses max(1,0)=1 so hp_summary shows ~99% instead of HP unknown."""
        from minion_comms.comms import set_context
        result = set_context(coder_agent, "working", hp=100)
        assert "hp" in result
        assert result["hp"] != "HP unknown"
        assert "99%" in result["hp"]

    def test_self_reported_hp_alert_fires_at_low_hp(self, isolated_db, lead_agent, coder_agent):
        """set_context(hp=20) → below 25% threshold → alert fires to lead."""
        from minion_comms.comms import set_context
        from minion_comms.db import get_db
        set_context(coder_agent, "working", hp=20)
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE from_agent = 'system' AND to_agent = ?",
                (lead_agent,),
            )
            assert cursor.fetchone()["cnt"] == 1
        finally:
            conn.close()


class TestHpAlerts:
    """Verify HP threshold alert messages are fired correctly by update_hp()."""

    def _message_count(self, recipient: str) -> int:
        """Count system→recipient messages in DB."""
        from minion_comms.db import get_db
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE from_agent = 'system' AND to_agent = ?",
                (recipient,),
            )
            return cursor.fetchone()["cnt"]
        finally:
            conn.close()

    def _hp_alerts_fired(self, agent_name: str) -> list[str]:
        """Return parsed hp_alerts_fired list from DB."""
        from minion_comms.db import get_db
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT hp_alerts_fired FROM agents WHERE name = ?", (agent_name,))
            row = cursor.fetchone()
            raw = row["hp_alerts_fired"] if row else None
            return json.loads(raw) if raw else []
        finally:
            conn.close()

    def test_25pct_alert_fires_at_24pct_hp(self, isolated_db, lead_agent, coder_agent):
        """24% HP crosses 25% threshold → alert message inserted for lead."""
        # 152000/200000 = 76% used → 24% HP
        update_hp(coder_agent, 152000, 5000, 200000, turn_input=152000)
        assert self._message_count(lead_agent) == 1

    def test_no_duplicate_alert_at_same_hp(self, isolated_db, lead_agent, coder_agent):
        """Second update_hp at same HP% → no second message inserted."""
        update_hp(coder_agent, 152000, 5000, 200000, turn_input=152000)
        update_hp(coder_agent, 152000, 5000, 200000, turn_input=152000)
        assert self._message_count(lead_agent) == 1

    def test_10pct_alert_fires_at_9pct_hp_after_25pct(self, isolated_db, lead_agent, coder_agent):
        """After 25% fires, 9% HP → only 10% alert fires (no dup 25%); 2 total messages."""
        # 152000/200000 → 24% HP → 25% fires
        update_hp(coder_agent, 152000, 5000, 200000, turn_input=152000)
        # 182000/200000 → 9% HP → 10% fires; 25% already in fired list
        update_hp(coder_agent, 182000, 5000, 200000, turn_input=182000)
        assert self._message_count(lead_agent) == 2
        fired = self._hp_alerts_fired(coder_agent)
        assert "25" in fired
        assert "10" in fired

    def test_hp_recovery_above_50pct_resets_alerts(self, isolated_db, lead_agent, coder_agent):
        """update_hp at 60% after alerts fired → hp_alerts_fired reset to []."""
        # Fire 25% alert
        update_hp(coder_agent, 152000, 5000, 200000, turn_input=152000)
        assert self._hp_alerts_fired(coder_agent) == ["25"]
        # 80000/200000 = 40% used → 60% HP → recovery resets list
        update_hp(coder_agent, 80000, 5000, 200000, turn_input=80000)
        assert self._hp_alerts_fired(coder_agent) == []

    def test_no_crash_when_no_lead(self, isolated_db, coder_agent):
        """No lead registered → update_hp succeeds without crash or messages."""
        result = update_hp(coder_agent, 152000, 5000, 200000, turn_input=152000)
        assert result["status"] == "ok"
        from minion_comms.db import get_db
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM messages WHERE from_agent = 'system'")
            assert cursor.fetchone()["cnt"] == 0
        finally:
            conn.close()
