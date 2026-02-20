"""Shared constants — env var names and default paths.

Single source of truth for path resolution across minion-comms
and minion-swarm. Both packages import from here.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Env var names
# ---------------------------------------------------------------------------

ENV_DB_PATH = "MINION_COMMS_DB_PATH"
ENV_DOCS_DIR = "MINION_DOCS_DIR"
ENV_PROJECT = "MINION_PROJECT"
ENV_CLASS = "MINION_CLASS"

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

WORK_ROOT = "~/.minion_work"
DEFAULT_DOCS_DIR = "~/.minion_work/docs"

# Project-local directory for intel, traps, code maps
COMMS_DIR_NAME = ".minion-comms"


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

def resolve_db_path() -> str:
    """Resolve DB path: ENV_DB_PATH > project-derived default."""
    explicit = os.getenv(ENV_DB_PATH)
    if explicit:
        return explicit
    project = os.getenv(ENV_PROJECT) or os.path.basename(os.getcwd())
    return os.path.expanduser(f"{WORK_ROOT}/{project}/minion.db")


def resolve_docs_dir() -> str:
    """Resolve docs dir: ENV_DOCS_DIR > default."""
    return os.getenv(ENV_DOCS_DIR, os.path.expanduser(DEFAULT_DOCS_DIR))
