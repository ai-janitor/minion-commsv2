"""Bridge to minion-tasks DAG engine with hardcoded fallback.

All DAG queries route through here. If minion-tasks is installed, uses
YAML-defined flows. Otherwise falls back to auth.VALID_TRANSITIONS constants.
"""

from __future__ import annotations

from typing import Any

from minion_comms.auth import TASK_STATUSES, VALID_TRANSITIONS

# Cache loaded flows so we don't re-parse YAML every call
_flow_cache: dict[str, Any] = {}

_HAS_DAG = False
try:
    from minion_tasks import TaskFlow, list_flows as _mt_list_flows, load_flow as _mt_load_flow
    _HAS_DAG = True
except ImportError:
    pass


def _get_flow(task_type: str = "bugfix") -> Any | None:
    """Load and cache a TaskFlow, or return None if unavailable."""
    if not _HAS_DAG:
        return None
    if task_type in _flow_cache:
        return _flow_cache[task_type]
    try:
        flow = _mt_load_flow(task_type)
        _flow_cache[task_type] = flow
        return flow
    except (FileNotFoundError, ValueError):
        _flow_cache[task_type] = None
        return None


# -- Terminal statuses (closed, abandoned, etc.) --

_FALLBACK_TERMINAL = {"closed"}
_FALLBACK_DEAD_ENDS = {"abandoned", "stale", "obsolete"}


def is_terminal(status: str, task_type: str = "bugfix") -> bool:
    """Is this status terminal (no further transitions)?"""
    flow = _get_flow(task_type)
    if flow is not None:
        return flow.is_terminal(status)
    return status in _FALLBACK_TERMINAL


def is_dead_end(status: str, task_type: str = "bugfix") -> bool:
    """Is this a dead-end status (abandoned/stale/obsolete)?"""
    flow = _get_flow(task_type)
    if flow is not None:
        return status in flow.dead_ends
    return status in _FALLBACK_DEAD_ENDS


# -- Status sets --

def all_statuses(task_type: str = "bugfix") -> set[str]:
    """All known statuses for this flow type."""
    flow = _get_flow(task_type)
    if flow is not None:
        return set(flow.stages.keys())
    return TASK_STATUSES


def active_statuses(task_type: str = "bugfix") -> tuple[str, ...]:
    """Non-terminal, non-dead-end statuses (what agents actively work on)."""
    flow = _get_flow(task_type)
    if flow is not None:
        return tuple(
            name for name, stage in flow.stages.items()
            if not stage.terminal and name not in flow.dead_ends
        )
    return ("open", "assigned", "in_progress", "fixed", "verified")


# -- Transitions --

def valid_transitions(current: str, task_type: str = "bugfix") -> set[str] | None:
    """Valid next statuses from current. None if current is unknown/terminal."""
    flow = _get_flow(task_type)
    if flow is not None:
        result = flow.valid_transitions(current)
        return result if result else None
    return VALID_TRANSITIONS.get(current)


def next_status(current: str, task_type: str = "bugfix", passed: bool = True) -> str | None:
    """DAG-driven next status. Returns None if terminal/unknown."""
    flow = _get_flow(task_type)
    if flow is not None:
        return flow.next_status(current, passed)
    # Fallback: simple linear pipeline
    _linear = {
        "open": "assigned",
        "assigned": "in_progress",
        "in_progress": "fixed",
        "fixed": "verified",
        "verified": "closed",
    }
    if not passed:
        return "assigned" if current in ("fixed", "verified") else None
    return _linear.get(current)


# -- Worker routing --

def workers_for(status: str, class_required: str, task_type: str = "bugfix") -> list[str] | None:
    """Which agent classes can work on this stage? None = current assignee continues."""
    flow = _get_flow(task_type)
    if flow is not None:
        return flow.workers_for(status, class_required)
    # Fallback: hardcoded routing
    _stage_workers: dict[str, list[str] | None] = {
        "open": None,
        "assigned": None,
        "in_progress": None,
        "fixed": ["oracle", "recon"],
        "verified": ["recon"],
    }
    return _stage_workers.get(status)


# -- Flow discovery --

def available_flows() -> list[str]:
    """List available flow type names."""
    if _HAS_DAG:
        try:
            return _mt_list_flows()
        except Exception:
            pass
    return ["bugfix"]
