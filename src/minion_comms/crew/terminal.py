"""Terminal transport — interactive claude session in its own Terminal.app window."""

from __future__ import annotations

import os

from minion_comms.crew._tmux import open_terminal_with_command


def spawn_terminal(
    agent: str,
    project_dir: str,
    cfg: dict,
) -> None:
    """Launch an interactive claude session in a new Terminal.app window."""
    system_prompt = cfg.get("system", "").strip()
    poll_instruction = (
        f"\n\nIMPORTANT: On startup, run `minion poll --agent {agent} &` "
        f"in the background to receive messages from other agents."
    )
    full_prompt = (system_prompt + poll_instruction) if system_prompt else ""

    cmd_parts = [f"cd {project_dir}", "claude --dangerously-skip-permissions"]
    if full_prompt:
        prompt_file = os.path.join(
            project_dir, ".minion-swarm", "prompts", f"{agent}.md"
        )
        os.makedirs(os.path.dirname(prompt_file), exist_ok=True)
        with open(prompt_file, "w") as pf:
            pf.write(full_prompt)
        cmd_parts[-1] += f" --append-system-prompt \"$(cat {prompt_file})\""
    cmd_parts[-1] += " \"Execute your ON STARTUP instructions now.\""

    open_terminal_with_command(" && ".join(cmd_parts), title=f"lead:{agent}")
