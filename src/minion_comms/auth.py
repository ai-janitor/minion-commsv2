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
