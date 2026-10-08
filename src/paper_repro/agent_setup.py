"""`setup`: register the MCP server with Claude Code, Codex and Cursor, and install the skill.

Shows the plan first. Changes nothing without ``apply=True``. Backs up any file it edits.
Safe to run twice.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path

from .util import run_capture

NAME = "paper-repro"
SERVER_CMD = ["uvx", NAME, "mcp"]


@dataclass
class Action:
    agent: str
    description: str
    target: str
    needed: bool
    apply: Callable[[], str] | None = None
    result: str | None = None


@dataclass
class Plan:
    detected: dict[str, bool] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)


def skill_text() -> str:
    try:
        return (resources.files("paper_repro") / "skill" / "SKILL.md").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "skills" / NAME / "SKILL.md"
        if cand.exists():
            return cand.read_text(encoding="utf-8")
    raise FileNotFoundError("SKILL.md not found in the package or the source tree")


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(f"{path.name}.bak-{NAME}-{stamp}")
    shutil.copy2(path, bak)
    return bak


def _write_skill(dest_dir: Path, text: str) -> Callable[[], str]:
    def go() -> str:
        dest = dest_dir / "SKILL.md"
        bak = _backup(dest)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return f"wrote {dest}" + (f" (backup {bak.name})" if bak else "")

    return go


def build_plan(
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    project_dir: Path | None = None,
) -> Plan:
    home = home or Path.home()
    plan = Plan()
    skill = skill_text()

    # ---- Claude Code
    claude_bin = which("claude")
    claude_dir = home / ".claude"
    has_claude = bool(claude_bin) or claude_dir.exists()
    plan.detected["claude-code"] = has_claude
    if has_claude:
        if project_dir is not None:
            mcp_json = project_dir / ".mcp.json"
            data = {}
            if mcp_json.exists():
                data = json.loads(mcp_json.read_text(encoding="utf-8") or "{}")
            present = NAME in data.get("mcpServers", {})

            def apply_project() -> str:
                d = (
                    json.loads(mcp_json.read_text(encoding="utf-8") or "{}")
                    if mcp_json.exists()
                    else {}
                )
                bak = _backup(mcp_json)
                d.setdefault("mcpServers", {})[NAME] = {
                    "command": SERVER_CMD[0],
                    "args": SERVER_CMD[1:],
                }
                mcp_json.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
                return f"updated {mcp_json}" + (f" (backup {bak.name})" if bak else "")

            plan.actions.append(
                Action(
                    "claude-code",
                    "add MCP server to project .mcp.json",
                    str(mcp_json),
                    not present,
                    apply_project,
                )
            )
        elif claude_bin:
            got = run_capture(
                [claude_bin, "mcp", "get", NAME], timeout=30, env=_env_with_home(home)
            )
            present = got["exit_code"] == 0
            cmd = [claude_bin, "mcp", "add", "--scope", "user", NAME, "--", *SERVER_CMD]

            def apply_cli() -> str:
                r = run_capture(cmd, timeout=60, env=_env_with_home(home))
                if r["exit_code"] != 0:
                    raise RuntimeError(f"`{' '.join(cmd)}` failed: {r['stderr'].strip()}")
                return f"ran: claude {' '.join(cmd[1:])}"

            plan.actions.append(
                Action(
                    "claude-code",
                    "register MCP server (user scope)",
                    "claude " + " ".join(cmd[1:]),
                    not present,
                    apply_cli,
                )
            )
        else:
            plan.actions.append(
                Action(
                    "claude-code",
                    "claude CLI not on PATH; run this yourself: claude mcp add --scope user "
                    f"{NAME} -- {' '.join(SERVER_CMD)}",
                    "(manual)",
                    False,
                )
            )
        if claude_dir.exists():
            dest = claude_dir / "skills" / NAME
            current = (
                (dest / "SKILL.md").read_text(encoding="utf-8")
                if (dest / "SKILL.md").exists()
                else None
            )
            plan.actions.append(
                Action(
                    "claude-code",
                    "install skill",
                    str(dest / "SKILL.md"),
                    current != skill,
                    _write_skill(dest, skill),
                )
            )

    # ---- Codex
    codex_dir = home / ".codex"
    has_codex = bool(which("codex")) or codex_dir.exists()
    plan.detected["codex"] = has_codex
    if has_codex:
        cfg = codex_dir / "config.toml"
        present = False
        if cfg.exists():
            try:
                present = NAME in tomllib.loads(cfg.read_text(encoding="utf-8")).get(
                    "mcp_servers", {}
                )
            except tomllib.TOMLDecodeError:
                present = f"[mcp_servers.{NAME}]" in cfg.read_text(encoding="utf-8")
        block = (
            f'\n[mcp_servers.{NAME}]\ncommand = "{SERVER_CMD[0]}"\n'
            f"args = [{', '.join(json.dumps(a) for a in SERVER_CMD[1:])}]\n"
        )

        def apply_codex() -> str:
            bak = _backup(cfg)
            codex_dir.mkdir(parents=True, exist_ok=True)
            existing = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
            sep = "" if not existing or existing.endswith("\n") else "\n"
            cfg.write_text(existing + sep + block, encoding="utf-8")
            return f"appended [mcp_servers.{NAME}] to {cfg}" + (
                f" (backup {bak.name})" if bak else ""
            )

        plan.actions.append(Action("codex", "add MCP server", str(cfg), not present, apply_codex))
        dest = codex_dir / "skills" / NAME
        current = (
            (dest / "SKILL.md").read_text(encoding="utf-8")
            if (dest / "SKILL.md").exists()
            else None
        )
        plan.actions.append(
            Action(
                "codex",
                "install skill",
                str(dest / "SKILL.md"),
                current != skill,
                _write_skill(dest, skill),
            )
        )

    # ---- Cursor
    cursor_dir = home / ".cursor"
    has_cursor = bool(which("cursor")) or cursor_dir.exists()
    plan.detected["cursor"] = has_cursor
    if has_cursor:
        mcp = cursor_dir / "mcp.json"
        data = {}
        if mcp.exists():
            try:
                data = json.loads(mcp.read_text(encoding="utf-8") or "{}")
            except json.JSONDecodeError:
                data = None  # type: ignore[assignment]
        if data is None:
            plan.actions.append(
                Action(
                    "cursor", f"{mcp} is not valid JSON; fix it, then rerun setup", str(mcp), False
                )
            )
        else:
            present = NAME in data.get("mcpServers", {})

            def apply_cursor() -> str:
                d = json.loads(mcp.read_text(encoding="utf-8") or "{}") if mcp.exists() else {}
                bak = _backup(mcp)
                cursor_dir.mkdir(parents=True, exist_ok=True)
                d.setdefault("mcpServers", {})[NAME] = {
                    "command": SERVER_CMD[0],
                    "args": SERVER_CMD[1:],
                }
                mcp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
                return f"updated {mcp}" + (f" (backup {bak.name})" if bak else "")

            plan.actions.append(
                Action("cursor", "add MCP server", str(mcp), not present, apply_cursor)
            )
    return plan


def _env_with_home(home: Path) -> dict:
    import os

    env = dict(os.environ)
    env["HOME"] = str(home)
    return env


def run_setup(
    apply: bool,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    project_dir: Path | None = None,
) -> dict:
    plan = build_plan(home=home, which=which, project_dir=project_dir)
    out = {"detected": plan.detected, "applied": apply, "actions": []}
    for a in plan.actions:
        item = {"agent": a.agent, "action": a.description, "target": a.target, "needed": a.needed}
        if apply and a.needed and a.apply:
            try:
                item["result"] = a.apply()
            except Exception as exc:  # report and continue with the other agents
                item["error"] = str(exc)
        elif not a.needed and a.apply:
            item["result"] = "already done"
        out["actions"].append(item)
    return out
