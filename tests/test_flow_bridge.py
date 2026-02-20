"""Tests for flow_bridge — fallback behavior and DAG integration."""

import pytest

from minion_comms.flow_bridge import (
    _flow_cache,
    all_statuses,
    available_flows,
    is_dead_end,
    is_terminal,
    next_status,
    valid_transitions,
    workers_for,
)


class TestFallbackBehavior:
    """When minion-tasks flow files aren't found, falls back to hardcoded constants."""

    def setup_method(self):
        _flow_cache.clear()

    def test_is_terminal_closed(self):
        assert is_terminal("closed") is True

    def test_is_terminal_open(self):
        assert is_terminal("open") is False

    def test_is_dead_end(self):
        assert is_dead_end("abandoned") is True
        assert is_dead_end("stale") is True
        assert is_dead_end("obsolete") is True
        assert is_dead_end("open") is False

    def test_all_statuses_contains_expected(self):
        statuses = all_statuses()
        for s in ("open", "assigned", "in_progress", "fixed", "verified", "closed"):
            assert s in statuses

    def test_valid_transitions_open(self):
        vt = valid_transitions("open")
        assert vt is not None
        assert "assigned" in vt

    def test_valid_transitions_terminal(self):
        # closed has no transitions in fallback
        vt = valid_transitions("closed")
        assert vt is None

    def test_next_status_linear(self):
        assert next_status("open") == "assigned"
        assert next_status("assigned") == "in_progress"
        assert next_status("in_progress") == "fixed"
        assert next_status("fixed") == "verified"
        assert next_status("verified") == "closed"

    def test_next_status_failed(self):
        assert next_status("fixed", passed=False) == "assigned"
        assert next_status("verified", passed=False) == "assigned"

    def test_workers_for_fixed(self):
        w = workers_for("fixed", "coder")
        assert w == ["oracle", "recon"]

    def test_workers_for_in_progress(self):
        # Current assignee continues
        assert workers_for("in_progress", "coder") is None

    def test_available_flows_fallback(self):
        flows = available_flows()
        assert "bugfix" in flows


class TestUnknownFlowFallback:
    """Unknown task_type gracefully falls back."""

    def setup_method(self):
        _flow_cache.clear()

    def test_unknown_type_falls_back(self):
        # nonexistent flow type should cache None and use fallback
        assert is_terminal("closed", "nonexistent_flow_xyz") is True
        assert next_status("open", "nonexistent_flow_xyz") == "assigned"
