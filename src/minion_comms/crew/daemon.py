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
            "-x", "220", "-y", "50",
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


def _find_ts_daemon_dir() -> str:
    """Locate ts-daemon directory: env var, then sibling of minion-swarm package."""
    if os.environ.get("MINION_TS_DAEMON_DIR"):
        return os.environ["MINION_TS_DAEMON_DIR"]
    try:
        import minion_swarm
        candidate = os.path.join(os.path.dirname(os.path.dirname(minion_swarm.__file__)), "ts-daemon")
        if os.path.isdir(candidate):
            return candidate
    except ImportError:
        pass
    return os.path.expanduser("~/.minion-swarm/ts-daemon")


def start_swarm(agent: str, crew_config: str, project_dir: str, runtime: str = "python") -> None:
    """Start daemon watcher for an agent.

    runtime='python' uses minion-swarm (original).
    runtime='ts' uses the TypeScript SDK daemon.
    """
    if runtime == "ts":
        log_file = os.path.join(project_dir, ".minion-swarm", "logs", f"{agent}.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        log_fp = open(log_file, "a")
        env = {**os.environ, "MINION_CLASS": "lead"}
        env.pop("CLAUDECODE", None)
        subprocess.Popen(
            ["npx", "tsx", "src/main.ts", "--config", crew_config, "--agent", agent],
            cwd=_find_ts_daemon_dir(),
            stdin=subprocess.DEVNULL,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
        log_fp.close()
    else:
        subprocess.run(
            ["minion-swarm", "start", agent, "--config", crew_config],
            cwd=project_dir, capture_output=True,
        )
