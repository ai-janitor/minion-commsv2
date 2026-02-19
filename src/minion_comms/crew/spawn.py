"""Spawn party — orchestrates crew creation from YAML."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from minion_comms.db import get_db
from minion_comms.crew._tmux import (
    finalize_layout,
    kill_all_crews,
    style_pane,
)
from minion_comms.crew.daemon import spawn_pane, start_swarm
from minion_comms.crew.terminal import spawn_terminal

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


def _role_to_class(role: str) -> str:
    """Map crew YAML role to agent class for registration."""
    return role if role in ("lead", "coder", "builder", "oracle", "recon") else "coder"


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
                agents_cfg = cfg.get("agents", {})
                leads = [n for n, c in agents_cfg.items() if c.get("role") == "lead"] or []
                if not leads:
                    legacy_lead = cfg.get("lead", {}).get("name")
                    if legacy_lead:
                        leads = [legacy_lead]
                members = {n: c.get("role", "?") for n, c in agents_cfg.items()}
                crews.append({"crew": crew_name, "lead": leads, "members": members})
            except Exception:
                crews.append({"crew": crew_name, "error": "parse failed"})

    return {"crews": crews}


def spawn_party(
    crew: str,
    project_dir: str = ".",
    agents: str = "",
) -> dict[str, object]:
    if not shutil.which("tmux"):
        return {"error": "BLOCKED: tmux required. brew install tmux"}
    if not shutil.which("minion-swarm"):
        return {"error": "BLOCKED: minion-swarm required."}

    crew_file = _find_crew_file(crew)
    if not crew_file:
        available: list[str] = []
        for d in CREW_SEARCH_PATHS:
            if os.path.isdir(d):
                available.extend(
                    f.replace(".yaml", "") for f in os.listdir(d)
                    if f.endswith(".yaml")
                )
        return {"error": f"BLOCKED: Crew '{crew}' not found. Available: {', '.join(sorted(set(available))) or 'none'}"}

    try:
        import yaml
    except ImportError:
        return {"error": "BLOCKED: PyYAML required. pip install pyyaml"}

    with open(crew_file) as f:
        crew_cfg = yaml.safe_load(f)

    project_dir = os.path.abspath(project_dir)
    crew_cfg["project_dir"] = project_dir

    # --- Backward compat: merge legacy lead: section into agents ---
    lead_cfg = crew_cfg.pop("lead", None)
    if lead_cfg and isinstance(lead_cfg, dict) and lead_cfg.get("name"):
        lead_name = lead_cfg["name"]
        agents_dict = crew_cfg.setdefault("agents", {})
        if lead_name not in agents_dict:
            agents_dict[lead_name] = {
                "role": lead_cfg.get("agent_class", "lead"),
                "transport": lead_cfg.get("transport", "terminal"),
                "zone": lead_cfg.get("zone", "Coordination & task management"),
                "provider": lead_cfg.get("provider", "claude"),
                "permission_mode": lead_cfg.get("permission_mode", "bypassPermissions"),
                "system": lead_cfg.get("system", ""),
            }

    all_agents_cfg = crew_cfg.get("agents", {})
    if not all_agents_cfg:
        return {"error": f"BLOCKED: No agents defined in crew '{crew}'."}

    all_agent_names = list(all_agents_cfg.keys())

    # --- Selective spawning ---
    selective = bool(agents)
    if selective:
        requested = [a.strip() for a in agents.split(",")]
        unknown = [a for a in requested if a not in all_agents_cfg]
        if unknown:
            return {"error": f"BLOCKED: Unknown agents: {', '.join(unknown)}. Available: {', '.join(sorted(all_agents_cfg))}"}
        all_agent_names = requested

    # Write runtime config for minion-swarm — exclude terminal agents
    swarm_cfg = dict(crew_cfg)
    swarm_cfg["agents"] = {
        name: cfg for name, cfg in all_agents_cfg.items()
        if cfg.get("transport", "daemon") != "terminal"
    }
    config_dir = os.path.expanduser("~/.minion-swarm")
    os.makedirs(config_dir, exist_ok=True)
    crew_config = os.path.join(config_dir, f"{crew}.yaml")
    with open(crew_config, "w") as f:
        yaml.dump(swarm_cfg, f, default_flow_style=False)

    subprocess.run(
        ["minion-swarm", "init", "--config", crew_config, "--project-dir", project_dir],
        capture_output=True,
    )

    if not selective:
        kill_all_crews()

    # --- Auto-register all agents, clear flags ---
    from minion_comms.comms import register as _register

    conn = get_db()
    try:
        conn.execute("DELETE FROM flags WHERE key = 'stand_down'")
        for a in all_agent_names:
            conn.execute("DELETE FROM agent_retire WHERE agent_name = ?", (a,))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM agents")
        registered = {row["name"] for row in cursor.fetchall()}
        conn.commit()
    finally:
        conn.close()

    for name in all_agent_names:
        cfg = all_agents_cfg[name]
        _register(
            agent_name=name,
            agent_class=_role_to_class(cfg.get("role", "coder")),
            transport=cfg.get("transport", "daemon"),
        )
        registered.add(name)

    # --- Name deconfliction for agents already registered by other crews ---
    spawn_agents: list[str] = []
    renames: dict[str, str] = {}
    for orig_name in all_agent_names:
        name = orig_name
        if name in registered and name not in all_agent_names:
            n = 2
            while f"{orig_name}{n}" in registered:
                n += 1
            name = f"{orig_name}{n}"
            renames[orig_name] = name
            agent_cfg = all_agents_cfg[orig_name].copy()
            if "system" in agent_cfg:
                agent_cfg["system"] = agent_cfg["system"].replace(
                    f'agent_name="{orig_name}"', f'agent_name="{name}"'
                ).replace(
                    f"You are {orig_name} ", f"You are {name} "
                )
            crew_cfg["agents"][name] = agent_cfg
            all_agents_cfg[name] = agent_cfg
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

    # --- Resolve roles and configs ---
    agent_roles: dict[str, str] = {}
    resolved_cfgs: dict[str, dict] = {}
    for name in spawn_agents:
        orig = next((k for k, v in renames.items() if v == name), name)
        cfg = all_agents_cfg.get(name) or all_agents_cfg.get(orig, {})
        agent_roles[name] = cfg.get("role", "")
        resolved_cfgs[name] = cfg

    # --- Spawn panes by transport type ---
    tmux_session = f"crew-{crew}"
    session_exists = subprocess.run(
        ["tmux", "has-session", "-t", tmux_session],
        capture_output=True,
    ).returncode == 0
    is_new = not session_exists

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

    pane_idx = existing_panes
    failed_agents: dict[str, str] = {}
    spawned_agents: list[str] = []
    for agent in spawn_agents:
        cfg = resolved_cfgs.get(agent, {})
        transport = cfg.get("transport", "daemon")

        if transport == "terminal":
            spawn_terminal(agent, project_dir, cfg)
            spawned_agents.append(agent)
            continue

        result = spawn_pane(tmux_session, agent, project_dir, crew_config, session_exists)
        if result is not True:
            failed_agents[agent] = result if isinstance(result, str) else "unknown error"
            continue
        session_exists = True
        spawned_agents.append(agent)

        style_pane(tmux_session, pane_idx, agent, agent_roles.get(agent, ""))
        pane_idx += 1

    finalize_layout(tmux_session, is_new)

    # Start minion-swarm for daemon agents (staggered to avoid API stampede)
    import time
    daemon_list = [
        a for a in spawned_agents
        if resolved_cfgs.get(a, {}).get("transport", "daemon") != "terminal"
    ]
    for i, agent in enumerate(daemon_list):
        if i > 0:
            time.sleep(0.25)
        start_swarm(agent, crew_config, project_dir)

    result_dict: dict[str, object] = {
        "status": "spawned",
        "agents": spawned_agents,
        "count": len(spawned_agents),
        "tmux_session": tmux_session,
    }
    if renames:
        result_dict["renames"] = renames
    if failed_agents:
        result_dict["failed"] = failed_agents
    return result_dict
