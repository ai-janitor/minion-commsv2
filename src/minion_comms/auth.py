"""Class-based authorization, constants, and gate functions."""

from __future__ import annotations

import os
import sys
from typing import Callable, TypeVar

import click

# ---------------------------------------------------------------------------
# Agent classes
# ---------------------------------------------------------------------------

VALID_CLASSES = {"lead", "coder", "builder", "oracle", "recon"}

# ---------------------------------------------------------------------------
# Model whitelist per class (empty set = any model allowed)
# ---------------------------------------------------------------------------

CLASS_MODEL_WHITELIST: dict[str, set[str]] = {
    "lead": {
        "claude-opus-4-6", "claude-opus-4-5",
        "claude-sonnet-4-6", "claude-sonnet-4-5",
        "gemini-pro", "gemini-1.5-pro", "gemini-2.0-pro",
    },
    "coder": {
        "claude-opus-4-6", "claude-opus-4-5",
        "claude-sonnet-4-6", "claude-sonnet-4-5",
        "gemini-pro", "gemini-1.5-pro", "gemini-2.0-pro",
    },
    "oracle": set(),
    "recon": set(),
    "builder": set(),
}

# ---------------------------------------------------------------------------
# Staleness thresholds (seconds) — enforced on send()
# ---------------------------------------------------------------------------

CLASS_STALENESS_SECONDS: dict[str, int] = {
    "coder": 5 * 60,
    "builder": 5 * 60,
    "recon": 5 * 60,
    "lead": 15 * 60,
    "oracle": 30 * 60,
}

# ---------------------------------------------------------------------------
# Battle plan / task / raid log enums
# ---------------------------------------------------------------------------

BATTLE_PLAN_STATUSES = {"active", "superseded", "completed", "abandoned", "obsolete"}

RAID_LOG_PRIORITIES = {"low", "normal", "high", "critical"}

TASK_STATUSES = {
    "open", "assigned", "in_progress", "fixed", "verified",
    "closed", "abandoned", "stale", "obsolete",
}

# ---------------------------------------------------------------------------
# Trigger words (brevity codes)
# ---------------------------------------------------------------------------

TRIGGER_WORDS: dict[str, str] = {
    "fenix_down": "Dump all knowledge to disk before context death. Revival protocol.",
    "moon_crash": "Emergency shutdown. Everyone fenix_down NOW. No new task assignments.",
    "sitrep": "Request status report from target agent.",
    "rally": "All agents focus on the specified target/zone.",
    "retreat": "Pull back from current approach, reassess.",
    "hot_zone": "Area is dangerous/complex, proceed with caution.",
    "stand_down": "Stop work, prepare to deregister.",
    "recon": "Investigate before acting. Gather intel first.",
}

# ---------------------------------------------------------------------------
# Briefing files per class (cold_start onboarding)
# ---------------------------------------------------------------------------

CLASS_BRIEFING_FILES: dict[str, list[str]] = {
    "lead": [".dead-drop/CODE_MAP.md", ".dead-drop/CODE_OWNERS.md", ".dead-drop/traps/"],
    "coder": [".dead-drop/CODE_MAP.md", ".dead-drop/traps/"],
    "builder": [".dead-drop/CODE_MAP.md", ".dead-drop/traps/"],
    "oracle": [".dead-drop/CODE_MAP.md", ".dead-drop/CODE_OWNERS.md", ".dead-drop/intel/", ".dead-drop/traps/"],
    "recon": [".dead-drop/CODE_MAP.md", ".dead-drop/intel/", ".dead-drop/traps/"],
}

# ---------------------------------------------------------------------------
# Tool catalog — command → (allowed_classes, description)
# ---------------------------------------------------------------------------

TOOL_CATALOG: dict[str, tuple[set[str], str]] = {
    "register":              (VALID_CLASSES, "Register an agent into the session"),
    "deregister":            (VALID_CLASSES, "Remove an agent from the registry"),
    "rename":                ({"lead"}, "Rename an agent (zone reassignment)"),
    "set-status":            (VALID_CLASSES, "Set your current status text"),
    "set-context":           (VALID_CLASSES, "Update context summary and HP metrics"),
    "who":                   (VALID_CLASSES, "List all registered agents"),
    "send":                  (VALID_CLASSES, "Send a message to an agent or broadcast"),
    "check-inbox":           (VALID_CLASSES, "Check and clear unread messages"),
    "get-history":           (VALID_CLASSES, "Return last N messages across all agents"),
    "purge-inbox":           (VALID_CLASSES, "Delete old messages from inbox"),
    "set-battle-plan":       ({"lead"}, "Set the active battle plan for the session"),
    "get-battle-plan":       (VALID_CLASSES, "Get battle plan by status"),
    "update-battle-plan-status": ({"lead"}, "Update a battle plan's status"),
    "log-raid":              (VALID_CLASSES, "Append an entry to the raid log"),
    "get-raid-log":          (VALID_CLASSES, "Read the raid log"),
    "create-task":           ({"lead"}, "Create a new task with spec file"),
    "assign-task":           ({"lead"}, "Assign a task to an agent"),
    "update-task":           (VALID_CLASSES, "Update task status, progress, or files"),
    "get-tasks":             (VALID_CLASSES, "List tasks with filters"),
    "get-task":              (VALID_CLASSES, "Get full detail for a single task"),
    "submit-result":         (VALID_CLASSES, "Submit a result file for a task"),
    "close-task":            ({"lead"}, "Close a completed task"),
    "claim-file":            ({"lead", "coder", "builder"}, "Claim a file for exclusive editing"),
    "release-file":          ({"lead", "coder", "builder"}, "Release a file claim"),
    "get-claims":            (VALID_CLASSES, "List active file claims"),
    "party-status":          ({"lead"}, "Full raid health dashboard"),
    "check-activity":        (VALID_CLASSES, "Check an agent's activity level"),
    "check-freshness":       ({"lead"}, "Check file freshness vs agent's last context"),
    "sitrep":                (VALID_CLASSES, "Fused COP: agents + tasks + claims + flags"),
    "update-hp":             ({"lead"}, "Daemon-only: write observed HP to SQLite"),
    "cold-start":            (VALID_CLASSES, "Bootstrap into a session, get onboarding"),
    "fenix-down":            (VALID_CLASSES, "Dump session knowledge before context death"),
    "debrief":               ({"lead"}, "File a session debrief"),
    "end-session":           ({"lead"}, "End the current session"),
    "get-triggers":          (VALID_CLASSES, "Return the trigger word codebook"),
    "clear-moon-crash":      ({"lead"}, "Clear emergency flag, resume assignments"),
    "list-crews":            ({"lead"}, "List available crew YAML files"),
    "spawn-party":           ({"lead"}, "Spawn daemon workers in tmux panes"),
    "stand-down":            ({"lead"}, "Dismiss the party"),
    "retire-agent":          ({"lead"}, "Signal a single daemon to exit gracefully"),
    "hand-off-zone":         (VALID_CLASSES, "Direct zone handoff between agents"),
    "tools":                 (VALID_CLASSES, "List available tools for your class"),
}


def get_tools_for_class(agent_class: str) -> list[dict[str, str]]:
    """Return tools available to a given class."""
    result = []
    for cmd, (classes, desc) in sorted(TOOL_CATALOG.items()):
        if agent_class in classes:
            result.append({"command": f"minion {cmd}", "description": desc})
    return result


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------

def get_agent_class() -> str:
    """Read MINION_CLASS from env, default to 'lead'."""
    return os.environ.get("MINION_CLASS", "lead")


F = TypeVar("F", bound=Callable[..., object])


def require_class(*allowed: str) -> Callable[[F], F]:
    """Decorator that gates a CLI command to specific agent classes.

    Checks MINION_CLASS env var. If the caller's class is not in *allowed*,
    prints an error and exits 1.
    """
    def decorator(func: F) -> F:
        import functools

        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            cls = get_agent_class()
            if cls not in allowed:
                click.echo(
                    f"BLOCKED: Class '{cls}' cannot run this command. "
                    f"Requires: {', '.join(sorted(allowed))}",
                    err=True,
                )
                sys.exit(1)
            return func(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator
