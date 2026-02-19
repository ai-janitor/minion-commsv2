"""Daemon transport — tmux pane with tail -f log, minion-swarm manages process."""

from __future__ import annotations

import os
import subprocess


def spawn_pane(
    tmux_session: str,
    agent: str,
    project_dir: str,
    crew_config: str,
    session_exists: bool,
) -> bool:
    """Create a tmux pane tailing the agent's log file.

    Returns True if pane was created, False if it didn't fit.
    """
    log_file = os.path.join(project_dir, ".minion-swarm", "logs", f"{agent}.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    open(log_file, "a").close()
    pane_cmd = f"tail -f {log_file}"

    if not session_exists:
        subprocess.run([
            "tmux", "new-session", "-d",
            "-s", tmux_session, "-n", agent,
            "bash", "-c", pane_cmd,
        ], check=True)
    else:
        # Rebalance layout before splitting so tmux has room for the new pane
        subprocess.run(
            ["tmux", "select-layout", "-t", tmux_session, "tiled"],
            capture_output=True,
        )
        result = subprocess.run([
            "tmux", "split-window", "-t", tmux_session,
            "bash", "-c", pane_cmd,
        ], capture_output=True, text=True)
        if result.returncode != 0:
            return result.stderr.strip()
    return True


def start_swarm(agent: str, crew_config: str, project_dir: str) -> None:
    """Start minion-swarm watcher for a daemon agent."""
    subprocess.run(
        ["minion-swarm", "start", agent, "--config", crew_config],
        cwd=project_dir, capture_output=True,
    )
