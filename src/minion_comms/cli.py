"""Click CLI entrypoint — `minion <subcommand>`.

Every call is stateless. JSON output by default, --human for tables.
MINION_CLASS env var gates commands via auth.require_class.
"""

from __future__ import annotations

import json
import os
import sys

import click

from minion_comms.db import init_db
from minion_comms.fs import ensure_dirs


def _output(data: dict[str, object], human: bool = False, compact: bool = False) -> None:
    """Print result as JSON (default), human-readable, or compact text."""
    if "error" in data:
        click.echo(json.dumps(data, indent=2, default=str), err=True)
        sys.exit(1)
    if compact:
        click.echo(_format_compact(data))
    elif human:
        for k, v in data.items():
            if isinstance(v, (list, dict)):
                click.echo(f"{k}: {json.dumps(v, indent=2, default=str)}")
            else:
                click.echo(f"{k}: {v}")
    else:
        click.echo(json.dumps(data, indent=2, default=str))


def _format_compact(data: dict[str, object]) -> str:
    """Format CLI output as concise text for agent context injection."""
    lines: list[str] = []

    # Status line
    status = data.get("status", "")
    agent = data.get("agent", data.get("agent_name", ""))
    cls = data.get("class", data.get("agent_class", ""))
    if status and agent:
        transport = ""
        playbook = data.get("playbook")
        if isinstance(playbook, dict):
            transport = f", {playbook.get('type', '')}"
        lines.append(f"{status}: {agent} ({cls}{transport})")

    # Tools as compact table
    tools = data.get("tools")
    if isinstance(tools, list) and tools:
        lines.append("")
        lines.append("Commands:")
        for t in tools:
            if isinstance(t, dict):
                cmd = t.get("command", "")
                desc = t.get("description", "")
                lines.append(f"  {cmd:30s} {desc}")

    # Triggers as one-liner
    triggers = data.get("triggers")
    if isinstance(triggers, str) and triggers:
        # Extract just the code words from the markdown table
        codes = []
        for line in triggers.splitlines():
            if line.startswith("| `"):
                code = line.split("`")[1]
                codes.append(code)
        if codes:
            lines.append("")
            lines.append(f"Triggers: {', '.join(codes)}")

    # Playbook as bullets
    playbook = data.get("playbook")
    if isinstance(playbook, dict):
        steps = playbook.get("steps", [])
        if steps:
            lines.append("")
            lines.append("Playbook:")
            for step in steps:
                lines.append(f"  - {step}")

    # Fall through for anything else
    if not lines:
        return json.dumps(data, indent=2, default=str)

    return "\n".join(lines)


@click.group()
@click.version_option(package_name="minion-comms")
@click.option("--human", is_flag=True, help="Human-readable output instead of JSON")
@click.option("--compact", is_flag=True, help="Concise text output for agent context injection")
@click.pass_context
def main(ctx: click.Context, human: bool, compact: bool) -> None:
    """minion — multi-agent coordination CLI."""
    ctx.ensure_object(dict)
    ctx.obj["human"] = human
    ctx.obj["compact"] = compact
    init_db()
    ensure_dirs()


# =========================================================================
# Core Comms (WP-02)
# =========================================================================

@main.command()
@click.option("--name", required=True)
@click.option("--class", "agent_class", required=True)
@click.option("--model", default="")
@click.option("--description", default="")
@click.option("--transport", default="terminal")
@click.pass_context
def register(ctx: click.Context, name: str, agent_class: str, model: str, description: str, transport: str) -> None:
    """Register an agent."""
    from minion_comms.comms import register as _register
    _output(_register(name, agent_class, model, description, transport), ctx.obj["human"], ctx.obj["compact"])


@main.command()
@click.option("--name", required=True)
@click.pass_context
def deregister(ctx: click.Context, name: str) -> None:
    """Remove an agent from the registry."""
    from minion_comms.comms import deregister as _deregister
    _output(_deregister(name), ctx.obj["human"])


@main.command()
@click.option("--old", required=True)
@click.option("--new", required=True)
@click.pass_context
def rename(ctx: click.Context, old: str, new: str) -> None:
    """Rename an agent. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.comms import rename as _rename
    _output(_rename(old, new), ctx.obj["human"])


@main.command("set-status")
@click.option("--agent", required=True)
@click.option("--status", required=True)
@click.pass_context
def set_status(ctx: click.Context, agent: str, status: str) -> None:
    """Set agent status."""
    from minion_comms.comms import set_status as _set_status
    _output(_set_status(agent, status), ctx.obj["human"])


@main.command("set-context")
@click.option("--agent", required=True)
@click.option("--context", required=True)
@click.option("--tokens-used", default=0, type=int)
@click.option("--tokens-limit", default=0, type=int)
@click.pass_context
def set_context(ctx: click.Context, agent: str, context: str, tokens_used: int, tokens_limit: int) -> None:
    """Update context summary and HP metrics."""
    from minion_comms.comms import set_context as _set_context
    _output(_set_context(agent, context, tokens_used, tokens_limit), ctx.obj["human"])


@main.command()
@click.pass_context
def who(ctx: click.Context) -> None:
    """List all registered agents."""
    from minion_comms.comms import who as _who
    _output(_who(), ctx.obj["human"])


@main.command()
@click.option("--from", "from_agent", required=True)
@click.option("--to", "to_agent", required=True)
@click.option("--message", required=True)
@click.option("--cc", default="")
@click.pass_context
def send(ctx: click.Context, from_agent: str, to_agent: str, message: str, cc: str) -> None:
    """Send a message to an agent (or 'all' for broadcast)."""
    from minion_comms.comms import send as _send
    _output(_send(from_agent, to_agent, message, cc), ctx.obj["human"])


@main.command("check-inbox")
@click.option("--agent", required=True)
@click.pass_context
def check_inbox(ctx: click.Context, agent: str) -> None:
    """Check and clear unread messages."""
    from minion_comms.comms import check_inbox as _check_inbox
    _output(_check_inbox(agent), ctx.obj["human"])


@main.command("get-history")
@click.option("--count", default=20, type=int)
@click.pass_context
def get_history(ctx: click.Context, count: int) -> None:
    """Return the last N messages across all agents."""
    from minion_comms.comms import get_history as _get_history
    _output(_get_history(count), ctx.obj["human"])


@main.command("purge-inbox")
@click.option("--agent", required=True)
@click.option("--older-than-hours", default=2, type=int)
@click.pass_context
def purge_inbox(ctx: click.Context, agent: str, older_than_hours: int) -> None:
    """Delete old messages from inbox."""
    from minion_comms.comms import purge_inbox as _purge_inbox
    _output(_purge_inbox(agent, older_than_hours), ctx.obj["human"])


# =========================================================================
# War Room (WP-03)
# =========================================================================

@main.command("set-battle-plan")
@click.option("--agent", required=True)
@click.option("--plan", required=True)
@click.pass_context
def set_battle_plan(ctx: click.Context, agent: str, plan: str) -> None:
    """Set the active battle plan. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.warroom import set_battle_plan as _set_battle_plan
    _output(_set_battle_plan(agent, plan), ctx.obj["human"])


@main.command("get-battle-plan")
@click.option("--status", default="active")
@click.pass_context
def get_battle_plan(ctx: click.Context, status: str) -> None:
    """Get battle plan by status."""
    from minion_comms.warroom import get_battle_plan as _get_battle_plan
    _output(_get_battle_plan(status), ctx.obj["human"])


@main.command("update-battle-plan-status")
@click.option("--agent", required=True)
@click.option("--plan-id", required=True, type=int)
@click.option("--status", required=True)
@click.pass_context
def update_battle_plan_status(ctx: click.Context, agent: str, plan_id: int, status: str) -> None:
    """Update a battle plan's status. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.warroom import update_battle_plan_status as _update
    _output(_update(agent, plan_id, status), ctx.obj["human"])


@main.command("log-raid")
@click.option("--agent", required=True)
@click.option("--entry", required=True)
@click.option("--priority", default="normal")
@click.pass_context
def log_raid(ctx: click.Context, agent: str, entry: str, priority: str) -> None:
    """Append an entry to the raid log."""
    from minion_comms.warroom import log_raid as _log_raid
    _output(_log_raid(agent, entry, priority), ctx.obj["human"])


@main.command("get-raid-log")
@click.option("--priority", default="")
@click.option("--count", default=20, type=int)
@click.option("--agent", default="")
@click.pass_context
def get_raid_log(ctx: click.Context, priority: str, count: int, agent: str) -> None:
    """Read the raid log."""
    from minion_comms.warroom import get_raid_log as _get_raid_log
    _output(_get_raid_log(priority, count, agent), ctx.obj["human"])


# =========================================================================
# Task System (WP-04)
# =========================================================================

@main.command("create-task")
@click.option("--agent", required=True)
@click.option("--title", required=True)
@click.option("--task-file", required=True)
@click.option("--project", default="")
@click.option("--zone", default="")
@click.option("--blocked-by", default="")
@click.pass_context
def create_task(ctx: click.Context, agent: str, title: str, task_file: str, project: str, zone: str, blocked_by: str) -> None:
    """Create a new task. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.tasks import create_task as _create_task
    _output(_create_task(agent, title, task_file, project, zone, blocked_by), ctx.obj["human"])


@main.command("assign-task")
@click.option("--agent", required=True)
@click.option("--task-id", required=True, type=int)
@click.option("--assigned-to", required=True)
@click.pass_context
def assign_task(ctx: click.Context, agent: str, task_id: int, assigned_to: str) -> None:
    """Assign a task to an agent. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.tasks import assign_task as _assign_task
    _output(_assign_task(agent, task_id, assigned_to), ctx.obj["human"])


@main.command("update-task")
@click.option("--agent", required=True)
@click.option("--task-id", required=True, type=int)
@click.option("--status", default="")
@click.option("--progress", default="")
@click.option("--files", default="")
@click.pass_context
def update_task(ctx: click.Context, agent: str, task_id: int, status: str, progress: str, files: str) -> None:
    """Update a task's status, progress, or files."""
    from minion_comms.tasks import update_task as _update_task
    _output(_update_task(agent, task_id, status, progress, files), ctx.obj["human"])


@main.command("get-tasks")
@click.option("--status", default="")
@click.option("--project", default="")
@click.option("--zone", default="")
@click.option("--assigned-to", default="")
@click.option("--count", default=50, type=int)
@click.pass_context
def get_tasks(ctx: click.Context, status: str, project: str, zone: str, assigned_to: str, count: int) -> None:
    """List tasks."""
    from minion_comms.tasks import get_tasks as _get_tasks
    _output(_get_tasks(status, project, zone, assigned_to, count), ctx.obj["human"])


@main.command("get-task")
@click.option("--task-id", required=True, type=int)
@click.pass_context
def get_task(ctx: click.Context, task_id: int) -> None:
    """Get full detail for a single task."""
    from minion_comms.tasks import get_task as _get_task
    _output(_get_task(task_id), ctx.obj["human"])


@main.command("submit-result")
@click.option("--agent", required=True)
@click.option("--task-id", required=True, type=int)
@click.option("--result-file", required=True)
@click.pass_context
def submit_result(ctx: click.Context, agent: str, task_id: int, result_file: str) -> None:
    """Submit a result file for a task."""
    from minion_comms.tasks import submit_result as _submit_result
    _output(_submit_result(agent, task_id, result_file), ctx.obj["human"])


@main.command("close-task")
@click.option("--agent", required=True)
@click.option("--task-id", required=True, type=int)
@click.pass_context
def close_task(ctx: click.Context, agent: str, task_id: int) -> None:
    """Close a task. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.tasks import close_task as _close_task
    _output(_close_task(agent, task_id), ctx.obj["human"])


# =========================================================================
# File Safety (WP-05)
# =========================================================================

@main.command("claim-file")
@click.option("--agent", required=True)
@click.option("--file", "file_path", required=True)
@click.pass_context
def claim_file(ctx: click.Context, agent: str, file_path: str) -> None:
    """Claim a file for exclusive editing."""
    from minion_comms.auth import require_class
    require_class("lead", "coder", "builder")(lambda: None)()
    from minion_comms.filesafety import claim_file as _claim_file
    _output(_claim_file(agent, file_path), ctx.obj["human"])


@main.command("release-file")
@click.option("--agent", required=True)
@click.option("--file", "file_path", required=True)
@click.option("--force", is_flag=True)
@click.pass_context
def release_file(ctx: click.Context, agent: str, file_path: str, force: bool) -> None:
    """Release a file claim."""
    from minion_comms.auth import require_class
    require_class("lead", "coder", "builder")(lambda: None)()
    from minion_comms.filesafety import release_file as _release_file
    _output(_release_file(agent, file_path, force), ctx.obj["human"])


@main.command("get-claims")
@click.option("--agent", default="")
@click.pass_context
def get_claims(ctx: click.Context, agent: str) -> None:
    """List active file claims."""
    from minion_comms.filesafety import get_claims as _get_claims
    _output(_get_claims(agent), ctx.obj["human"])


# =========================================================================
# Monitoring (WP-06)
# =========================================================================

@main.command("party-status")
@click.pass_context
def party_status_cmd(ctx: click.Context) -> None:
    """Full raid health dashboard. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.monitoring import party_status
    _output(party_status(), ctx.obj["human"])


@main.command("check-activity")
@click.option("--agent", required=True)
@click.pass_context
def check_activity(ctx: click.Context, agent: str) -> None:
    """Check an agent's activity level."""
    from minion_comms.monitoring import check_activity as _check_activity
    _output(_check_activity(agent), ctx.obj["human"])


@main.command("check-freshness")
@click.option("--agent", required=True)
@click.option("--files", required=True)
@click.pass_context
def check_freshness(ctx: click.Context, agent: str, files: str) -> None:
    """Check file freshness relative to agent's last set-context. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.monitoring import check_freshness as _check_freshness
    _output(_check_freshness(agent, files), ctx.obj["human"])


@main.command()
@click.pass_context
def sitrep(ctx: click.Context) -> None:
    """Fused COP: agents + tasks + zones + claims + flags + recent comms."""
    from minion_comms.monitoring import sitrep as _sitrep
    _output(_sitrep(), ctx.obj["human"])


@main.command("update-hp")
@click.option("--agent", required=True)
@click.option("--input-tokens", required=True, type=int)
@click.option("--output-tokens", required=True, type=int)
@click.option("--limit", required=True, type=int)
@click.option("--turn-input", default=None, type=int, help="Per-turn input tokens (current context pressure)")
@click.option("--turn-output", default=None, type=int, help="Per-turn output tokens (current context pressure)")
@click.pass_context
def update_hp(ctx: click.Context, agent: str, input_tokens: int, output_tokens: int, limit: int, turn_input: int | None, turn_output: int | None) -> None:
    """Daemon-only: write observed HP to SQLite."""
    from minion_comms.monitoring import update_hp as _update_hp
    _output(_update_hp(agent, input_tokens, output_tokens, limit, turn_input, turn_output), ctx.obj["human"])


# =========================================================================
# Lifecycle (WP-07)
# =========================================================================

@main.command("cold-start")
@click.option("--agent", required=True)
@click.pass_context
def cold_start(ctx: click.Context, agent: str) -> None:
    """Bootstrap an agent into (or back into) a session."""
    from minion_comms.lifecycle import cold_start as _cold_start
    _output(_cold_start(agent), ctx.obj["human"], ctx.obj["compact"])


@main.command("fenix-down")
@click.option("--agent", required=True)
@click.option("--files", required=True)
@click.option("--manifest", default="")
@click.pass_context
def fenix_down(ctx: click.Context, agent: str, files: str, manifest: str) -> None:
    """Dump session knowledge to disk before context death."""
    from minion_comms.lifecycle import fenix_down as _fenix_down
    _output(_fenix_down(agent, files, manifest), ctx.obj["human"])


@main.command()
@click.option("--agent", required=True)
@click.option("--debrief-file", required=True)
@click.pass_context
def debrief(ctx: click.Context, agent: str, debrief_file: str) -> None:
    """File a session debrief. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.lifecycle import debrief as _debrief
    _output(_debrief(agent, debrief_file), ctx.obj["human"])


@main.command("end-session")
@click.option("--agent", required=True)
@click.pass_context
def end_session(ctx: click.Context, agent: str) -> None:
    """End the current session. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.lifecycle import end_session as _end_session
    _output(_end_session(agent), ctx.obj["human"])


# =========================================================================
# Triggers (WP-08)
# =========================================================================

@main.command("get-triggers")
@click.pass_context
def get_triggers(ctx: click.Context) -> None:
    """Return the trigger word codebook."""
    from minion_comms.triggers import get_triggers as _get_triggers
    _output(_get_triggers(), ctx.obj["human"])


@main.command("clear-moon-crash")
@click.option("--agent", required=True)
@click.pass_context
def clear_moon_crash(ctx: click.Context, agent: str) -> None:
    """Clear the moon_crash emergency flag. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.triggers import clear_moon_crash as _clear
    _output(_clear(agent), ctx.obj["human"])


# =========================================================================
# Crew (WP-08)
# =========================================================================

@main.command("list-crews")
@click.pass_context
def list_crews(ctx: click.Context) -> None:
    """List available crews. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.crew import list_crews as _list_crews
    _output(_list_crews(), ctx.obj["human"])


@main.command("spawn-party")
@click.option("--crew", required=True)
@click.option("--project-dir", default=".")
@click.option("--agents", default="")
@click.pass_context
def spawn_party(ctx: click.Context, crew: str, project_dir: str, agents: str) -> None:
    """Spawn daemon workers in tmux panes. Auto-registers lead from crew YAML."""
    from minion_comms.crew import spawn_party as _spawn_party
    _output(_spawn_party(crew, project_dir, agents), ctx.obj["human"])


@main.command("stand-down")
@click.option("--agent", required=True)
@click.option("--crew", default="")
@click.pass_context
def stand_down(ctx: click.Context, agent: str, crew: str) -> None:
    """Dismiss the party. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.crew import stand_down as _stand_down
    _output(_stand_down(agent, crew), ctx.obj["human"])


@main.command("retire-agent")
@click.option("--agent", required=True, help="Agent to retire")
@click.option("--requesting-agent", required=True, help="Lead requesting retirement")
@click.pass_context
def retire_agent_cmd(ctx: click.Context, agent: str, requesting_agent: str) -> None:
    """Signal a single daemon agent to exit gracefully. Lead only."""
    from minion_comms.auth import require_class
    require_class("lead")(lambda: None)()
    from minion_comms.crew import retire_agent as _retire_agent
    _output(_retire_agent(agent, requesting_agent), ctx.obj["human"])


@main.command("hand-off-zone")
@click.option("--from", "from_agent", required=True)
@click.option("--to", "to_agents", required=True, help="Comma-separated agent names")
@click.option("--zone", required=True)
@click.pass_context
def hand_off_zone(ctx: click.Context, from_agent: str, to_agents: str, zone: str) -> None:
    """Direct zone handoff — retiring agent bestows zone to replacements."""
    from minion_comms.crew import hand_off_zone as _hand_off
    _output(_hand_off(from_agent, to_agents, zone), ctx.obj["human"])


# =========================================================================
# Discovery
# =========================================================================

@main.command()
@click.option("--class", "agent_class", default="", help="Class to list tools for (default: MINION_CLASS env)")
@click.pass_context
def tools(ctx: click.Context, agent_class: str) -> None:
    """List available tools for your class."""
    from minion_comms.auth import get_agent_class, get_tools_for_class
    cls = agent_class or get_agent_class()
    docs_dir = os.path.expanduser("~/.minion-comms/docs")
    protocol_file = f"protocol-{cls}.md"
    result: dict[str, object] = {
        "class": cls,
        "tools": get_tools_for_class(cls),
        "protocol_doc": os.path.join(docs_dir, protocol_file) if os.path.isfile(os.path.join(docs_dir, protocol_file)) else None,
    }
    _output(result, ctx.obj["human"], ctx.obj["compact"])


if __name__ == "__main__":
    main()
