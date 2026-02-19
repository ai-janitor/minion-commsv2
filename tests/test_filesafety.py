"""Tests for file safety: claim, release, get_claims."""

from minion_comms.comms import register
from minion_comms.filesafety import claim_file, get_claims, release_file


class TestClaimFile:
    def test_claim_success(self, isolated_db):
        register("coder1", "coder")
        result = claim_file("coder1", "/tmp/test.py")
        assert result["status"] == "claimed"

    def test_claim_already_owned(self, isolated_db):
        register("coder1", "coder")
        claim_file("coder1", "/tmp/test.py")
        result = claim_file("coder1", "/tmp/test.py")
        assert result["status"] == "already_claimed"

    def test_claim_blocked_by_other(self, isolated_db):
        register("coder1", "coder")
        register("coder2", "coder")
        claim_file("coder1", "/tmp/test.py")
        result = claim_file("coder2", "/tmp/test.py")
        assert "error" in result
        assert "BLOCKED" in result["error"]

    def test_claim_unregistered(self, isolated_db):
        result = claim_file("ghost", "/tmp/test.py")
        assert "error" in result


class TestReleaseFile:
    def test_release_success(self, isolated_db):
        register("coder1", "coder")
        claim_file("coder1", "/tmp/test.py")
        result = release_file("coder1", "/tmp/test.py")
        assert result["status"] == "released"

    def test_release_not_claimed(self, isolated_db):
        register("coder1", "coder")
        result = release_file("coder1", "/tmp/test.py")
        assert "error" in result

    def test_release_by_other_blocked(self, isolated_db):
        register("coder1", "coder")
        register("coder2", "coder")
        claim_file("coder1", "/tmp/test.py")
        result = release_file("coder2", "/tmp/test.py")
        assert "error" in result

    def test_force_release_by_lead(self, isolated_db):
        register("coder1", "coder")
        register("boss", "lead")
        claim_file("coder1", "/tmp/test.py")
        result = release_file("boss", "/tmp/test.py", force=True)
        assert result["status"] == "released"
        assert result["force_released_by"] == "boss"


class TestGetClaims:
    def test_get_claims_empty(self, isolated_db):
        result = get_claims()
        assert result["claims"] == []

    def test_get_claims_filtered(self, isolated_db):
        register("coder1", "coder")
        register("coder2", "coder")
        claim_file("coder1", "/tmp/a.py")
        claim_file("coder2", "/tmp/b.py")
        result = get_claims("coder1")
        assert len(result["claims"]) == 1
