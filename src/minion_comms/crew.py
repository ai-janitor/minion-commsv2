"""Crew — list_crews, spawn_party, stand_down, retire_agent, hand_off_zone."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from minion_comms.comms import deregister
from minion_comms.db import get_db, now_iso

CREW_SEARCH_PATHS = [
    os.path.expanduser("~/.minion-swarm/crews"),
    os.path.expanduser("~/.minion-swarm"),
]

# Try bundled crews from minion-swarm package
try:
    import minion_swarm
    _pkg_crews = os.path.join(os.path.dirname(minion_swarm.__file__), "data", "crews")
    if os.path.isdir(_pkg_crews):
        CREW_SEARCH_PATHS.insert(0, _pkg_crews)
except ImportError:
    pass


def _find_crew_file(crew_name: str) -> str | None:
    for d in CREW_SEARCH_PATHS:
        candidate = os.path.join(d, f"{crew_name}.yaml")
        if os.path.isfile(candidate):
            return candidate
    return None


def _spawn_tmux_workers(
    crew_name: str,
    agents: list[str],
    crew_config: str,
    project_dir: str,
    agent_roles: dict[str, str] | None = None,
) -> str:
    tmux_session = f"crew-{crew_name}"

    session_exists = subprocess.run(
        ["tmux", "has-session", "-t", tmux_session],
        capture_output=True,
    ).returncode == 0

    if not session_exists:
        logs_dir = os.path.join(project_dir, ".minion-swarm", "logs")
        if os.path.isdir(logs_dir):
            for fname in os.listdir(logs_dir):
                if fname.endswith(".log"):
                    open(os.path.join(logs_dir, fname), "w").close()

    existing_panes = 0
    if session_exists:
        result = subprocess.run(
            ["tmux", "list-panes", "-t", tmux_session],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            existing_panes = len(result.stdout.strip().splitlines())

    for i, agent in enumerate(agents):
        log_file = os.path.join(project_dir, ".minion-swarm", "logs", f"{agent}.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        open(log_file, "a").close()
        pane_cmd = f"tail -f {log_file}"

        if not session_exists and i == 0:
            subprocess.run([
                "tmux", "new-session", "-d",
                "-s", tmux_session, "-n", agent,
                "bash", "-c", pane_cmd,
            ], check=True)
            session_exists = True
        else:
            subprocess.run([
                "tmux", "split-window", "-t", tmux_session, "-v",
                "bash", "-c", pane_cmd,
            ], check=True)

        pane_idx = existing_panes + i
        role = (agent_roles or {}).get(agent, "")
        pane_title = f"{agent}({role})" if role else agent
        subprocess.run([
            "tmux", "select-pane", "-t", f"{tmux_session}:{0}.{pane_idx}", "-T", pane_title,
        ], capture_output=True)

    subprocess.run(["tmux", "select-layout", "-t", tmux_session, "tiled"], capture_output=True)
    subprocess.run(["tmux", "set-option", "-t", tmux_session, "pane-border-status", "top"], capture_output=True)
    subprocess.run(["tmux", "set-option", "-t", tmux_session, "pane-border-format", " #{pane_title} "], capture_output=True)

    if existing_panes == 0:
        _open_tmux_terminal(tmux_session)

    for agent in agents:
        subprocess.run(
            ["minion-swarm", "start", agent, "--config", crew_config],
            cwd=project_dir, capture_output=True,
        )

    return tmux_session


def _open_tmux_terminal(tmux_session: str) -> None:
    import platform
    if platform.system() != "Darwin":
        return
    title = f"workers:{tmux_session}"
    escaped_cmd = f"tmux attach -t {tmux_session}".replace('"', '\\"')
    script = f'''
    tell application "Terminal"
        activate
        do script "{escaped_cmd}"
        set custom title of front window to "{title}"
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def _close_terminal_by_title(title: str) -> None:
    import platform
    if platform.system() != "Darwin":
        return
    script = f'''
    tell application "Terminal"
        repeat with w in windows
            if custom title of w contains "{title}" then
                close w saving no
            end if
        end repeat
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True)


def _kill_all_crews() -> None:
    config_dir = os.path.expanduser("~/.minion-swarm")
    if os.path.isdir(config_dir):
        for fname in os.listdir(config_dir):
            if fname.endswith(".yaml"):
                subprocess.run(
                    ["minion-swarm", "stop", "--config", os.path.join(config_dir, fname)],
                    capture_output=True,
                )

    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        for session in result.stdout.strip().splitlines():
            if session.startswith("crew-"):
                _close_terminal_by_title(f"workers:{session}")
                subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)


def _kill_tmux_pane_by_title(agent_name: str) -> None:
    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{session_name}:#{window_name}.#{pane_index} #{pane_title}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return
        for line in result.stdout.strip().splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2:
                title = parts[1]
                if title == agent_name or title.startswith(f"{agent_name}("):
                    subprocess.run(["tmux", "kill-pane", "-t", parts[0]], capture_output=True)
                    return
    except FileNotFoundError:
        pass


def list_crews() -> dict[str, object]:
    try:
        import yaml
    except ImportError:
        return {"error": "PyYAML required. pip install pyyaml"}

    seen: set[str] = set()
    crews: list[dict[str, Any]] = []
    for d in CREW_SEARCH_PATHS:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".yaml"):
                continue
            crew_name = fname.replace(".yaml", "")
            if crew_name in seen:
                continue
            seen.add(crew_name)
            try:
                with open(os.path.join(d, fname)) as f:
                    cfg = yaml.safe_load(f)
                lead = cfg.get("lead", {}).get("name", "?")
                agents_cfg = cfg.get("agents", {})
                members = {n: c.get("role", "?") for n, c in agents_cfg.items()}
                crews.append({"crew": crew_name, "lead": lead, "members": members})
            except Exception:
                crews.append({"crew": crew_name, "error": "parse failed"})

    return {"crews": crews}


def spawn_party(
    agent_name: str,
    crew: str,
    project_dir: str = ".",
    agents: str = "",
) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can spawn a party. '{agent_name}' is '{row['agent_class']}'."}
    finally:
        conn.close()

    if not shutil.which("tmux"):
        return {"error": "BLOCKED: tmux required. brew install tmux"}
    if not shutil.which("minion-swarm"):
        return {"error": "BLOCKED: minion-swarm required."}

    crew_file = _find_crew_file(crew)
    if not crew_file:
        available: list[str] = []
        for d in CREW_SEARCH_PATHS:
            if os.path.isdir(d):
                available.extend(f.replace(".yaml", "") for f in os.listdir(d) if f.endswith(".yaml"))
        return {"error": f"BLOCKED: Crew '{crew}' not found. Available: {', '.join(sorted(set(available))) or 'none'}"}

    try:
        import yaml
    except ImportError:
        return {"error": "BLOCKED: PyYAML required. pip install pyyaml"}

    with open(crew_file) as f:
        crew_cfg = yaml.safe_load(f)

    project_dir = os.path.abspath(project_dir)
    crew_cfg["project_dir"] = project_dir

    lead_cfg = crew_cfg.get("lead", {})
    lead_name = lead_cfg.get("name")

    all_agents = list(crew_cfg.get("agents", {}).keys())
    spawnable = set(all_agents)
    if lead_name:
        spawnable.add(lead_name)

    if not spawnable:
        return {"error": f"BLOCKED: No agents defined in crew '{crew}'."}

    selective = bool(agents)
    if selective:
        requested = [a.strip() for a in agents.split(",")]
        unknown = [a for a in requested if a not in spawnable]
        if unknown:
            return {"error": f"BLOCKED: Unknown agents: {', '.join(unknown)}. Available: {', '.join(sorted(spawnable))}"}
        if lead_name and lead_name in requested and lead_name not in crew_cfg.get("agents", {}):
            crew_cfg.setdefault("agents", {})[lead_name] = {
                "role": lead_cfg.get("agent_class", "lead"),
                "zone": "Coordination & task management",
                "provider": "claude",
                "permission_mode": "bypassPermissions",
                "system": lead_cfg.get("system", ""),
            }
            all_agents.append(lead_name)
        all_agents = requested

    config_dir = os.path.expanduser("~/.minion-swarm")
    os.makedirs(config_dir, exist_ok=True)
    crew_config = os.path.join(config_dir, f"{crew}.yaml")
    with open(crew_config, "w") as f:
        yaml.dump(crew_cfg, f, default_flow_style=False)

    subprocess.run(
        ["minion-swarm", "init", "--config", crew_config, "--project-dir", project_dir],
        capture_output=True,
    )

    if not selective:
        _kill_all_crews()

    conn = get_db()
    try:
        conn.execute("DELETE FROM flags WHERE key = 'stand_down'")
        for a in all_agents:
            conn.execute("DELETE FROM agent_retire WHERE agent_name = ?", (a,))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM agents")
        registered = {row["name"] for row in cursor.fetchall()}
        conn.commit()
    finally:
        conn.close()

    spawn_agents: list[str] = []
    renames: dict[str, str] = {}
    for orig_name in all_agents:
        name = orig_name
        if name in registered:
            n = 2
            while f"{orig_name}{n}" in registered:
                n += 1
            name = f"{orig_name}{n}"
            renames[orig_name] = name
            agent_cfg = crew_cfg["agents"][orig_name].copy()
            if "system" in agent_cfg:
                agent_cfg["system"] = agent_cfg["system"].replace(
                    f'agent_name="{orig_name}"', f'agent_name="{name}"'
                ).replace(
                    f"You are {orig_name} ", f"You are {name} "
                )
            crew_cfg["agents"][name] = agent_cfg
        spawn_agents.append(name)
        registered.add(name)

    if renames:
        import tempfile
        runtime_config = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", prefix=f"crew-{crew}-",
            dir=os.path.dirname(crew_config), delete=False,
        )
        yaml.dump(crew_cfg, runtime_config, default_flow_style=False)
        runtime_config.close()
        crew_config = runtime_config.name

    agent_roles: dict[str, str] = {}
    for name in spawn_agents:
        orig = next((k for k, v in renames.items() if v == name), name)
        cfg = crew_cfg.get("agents", {}).get(name) or crew_cfg.get("agents", {}).get(orig, {})
        agent_roles[name] = cfg.get("role", "")
        if not agent_roles[name] and lead_name and (name == lead_name or orig == lead_name):
            agent_roles[name] = lead_cfg.get("agent_class", "lead")

    tmux_session = _spawn_tmux_workers(crew, spawn_agents, crew_config, project_dir, agent_roles)

    result: dict[str, object] = {
        "status": "spawned",
        "agents": spawn_agents,
        "count": len(spawn_agents),
        "tmux_session": tmux_session,
    }
    if renames:
        result["renames"] = renames
    return result


def stand_down(agent_name: str, crew: str = "") -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (agent_name,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{agent_name}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can stand_down. '{agent_name}' is '{row['agent_class']}'."}

        cursor.execute(
            """INSERT INTO flags (key, value, set_by, set_at)
               VALUES ('stand_down', '1', ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = '1', set_by = excluded.set_by, set_at = excluded.set_at""",
            (agent_name, now),
        )
        conn.commit()
    finally:
        conn.close()

    if crew:
        config_path = os.path.expanduser(f"~/.minion-swarm/{crew}.yaml")
        if os.path.isfile(config_path):
            subprocess.run(["minion-swarm", "stop", "--config", config_path], capture_output=True)
        _close_terminal_by_title(f"workers:crew-{crew}")
        subprocess.run(["tmux", "kill-session", "-t", f"crew-{crew}"], capture_output=True)
        return {"status": "dismissed", "crew": crew}
    else:
        _kill_all_crews()
        return {"status": "dismissed", "crew": "all"}


def retire_agent(agent_name: str, requesting_agent: str) -> dict[str, object]:
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT agent_class FROM agents WHERE name = ?", (requesting_agent,))
        row = cursor.fetchone()
        if not row:
            return {"error": f"BLOCKED: Agent '{requesting_agent}' not registered."}
        if row["agent_class"] != "lead":
            return {"error": f"BLOCKED: Only lead-class agents can retire agents. '{requesting_agent}' is '{row['agent_class']}'."}

        cursor.execute(
            """INSERT INTO agent_retire (agent_name, set_at, set_by)
               VALUES (?, ?, ?)
               ON CONFLICT(agent_name) DO UPDATE SET set_at = excluded.set_at, set_by = excluded.set_by""",
            (agent_name, now, requesting_agent),
        )
        conn.commit()
    finally:
        conn.close()

    deregister(agent_name)
    _kill_tmux_pane_by_title(agent_name)

    return {"status": "retired", "agent": agent_name, "by": requesting_agent}


def hand_off_zone(
    from_agent: str,
    to_agents: str,
    zone: str,
) -> dict[str, object]:
    """Direct zone handoff — retiring agent bestows zone to replacements."""
    conn = get_db()
    cursor = conn.cursor()
    now = now_iso()
    try:
        cursor.execute("SELECT name FROM agents WHERE name = ?", (from_agent,))
        if not cursor.fetchone():
            return {"error": f"BLOCKED: Agent '{from_agent}' not registered."}

        targets = [a.strip() for a in to_agents.split(",") if a.strip()]
        if not targets:
            return {"error": "BLOCKED: No target agents specified."}

        missing = []
        for t in targets:
            cursor.execute("SELECT name FROM agents WHERE name = ?", (t,))
            if not cursor.fetchone():
                missing.append(t)
        if missing:
            return {"error": f"BLOCKED: Agents not registered: {', '.join(missing)}"}

        # Update zone assignments
        for t in targets:
            cursor.execute(
                "UPDATE agents SET current_zone = ?, last_seen = ? WHERE name = ?",
                (zone, now, t),
            )

        # Clear from_agent's zone
        cursor.execute(
            "UPDATE agents SET current_zone = NULL, last_seen = ? WHERE name = ?",
            (now, from_agent),
        )

        # Log to raid log
        from minion_comms.fs import atomic_write_file, raid_log_file_path
        entry = f"ZONE HANDOFF: {from_agent} → {', '.join(targets)} | zone: {zone}"
        entry_file = raid_log_file_path(from_agent, "high")
        atomic_write_file(entry_file, entry)

        cursor.execute(
            """INSERT INTO raid_log (agent_name, entry_file, priority, created_at)
               VALUES (?, ?, 'high', ?)""",
            (from_agent, entry_file, now),
        )

        conn.commit()

        return {
            "status": "handed_off",
            "from": from_agent,
            "to": targets,
            "zone": zone,
        }
    finally:
        conn.close()
