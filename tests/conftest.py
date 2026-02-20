"""Shared test fixtures — temp DB + temp filesystem per test."""

import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Give each test its own DB and filesystem directories."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("MINION_COMMS_DB_PATH", db_path)

    # Patch the module-level DB_PATH and RUNTIME_DIR
    import minion_comms.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(db_mod, "DOCS_DIR", str(tmp_path / "docs"))

    import minion_comms.fs as fs_mod
    monkeypatch.setattr(fs_mod, "INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setattr(fs_mod, "BATTLE_PLAN_DIR", str(tmp_path / "battle-plans"))
    monkeypatch.setattr(fs_mod, "RAID_LOG_DIR", str(tmp_path / "raid-log"))

    from minion_comms.db import init_db
    from minion_comms.fs import ensure_dirs
    init_db()
    ensure_dirs()

    return db_path


@pytest.fixture
def lead_agent():
    """Register a lead agent for tests that need one."""
    from minion_comms.comms import register
    register("lead", "lead")
    return "lead"


@pytest.fixture
def coder_agent():
    """Register a coder agent."""
    from minion_comms.comms import register
    register("coder1", "coder")
    return "coder1"


@pytest.fixture
def battle_plan(lead_agent):
    """Set up an active battle plan (required for send)."""
    from minion_comms.warroom import set_battle_plan
    result = set_battle_plan(lead_agent, "Test battle plan")
    return result
