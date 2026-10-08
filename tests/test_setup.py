import json
import os
import stat
import tomllib

from paper_repro.agent_setup import run_setup, skill_text


def fake_claude(bin_dir, log):
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$2" = "get" ]; then grep -q "^mcp add" "' + str(log) + '" && exit 0; exit 1; fi\n'
        "exit 0\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_dry_run_changes_nothing_then_apply_then_idempotent(tmp_path):
    home = tmp_path / "home2"
    for d in (".claude", ".codex", ".cursor"):
        (home / d).mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text('model = "o4"\n')
    (home / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "x"}}})
    )
    log = tmp_path / "claude.log"
    claude = fake_claude(tmp_path / "bin", log)

    def which(name):
        return claude if name == "claude" else None

    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    plan = run_setup(apply=False, home=home, which=which)
    assert plan["detected"] == {"claude-code": True, "codex": True, "cursor": True}
    assert all(a["needed"] for a in plan["actions"])
    assert {p: p.read_bytes() for p in home.rglob("*") if p.is_file()} == before
    assert "mcp add" not in (log.read_text() if log.exists() else "")

    done = run_setup(apply=True, home=home, which=which)
    assert not any("error" in a for a in done["actions"]), done
    assert "mcp add --scope user paper-repro -- uvx paper-repro mcp" in log.read_text()
    cfg = tomllib.loads((home / ".codex" / "config.toml").read_text())
    assert cfg["model"] == "o4"
    assert cfg["mcp_servers"]["paper-repro"] == {"command": "uvx", "args": ["paper-repro", "mcp"]}
    cur = json.loads((home / ".cursor" / "mcp.json").read_text())
    assert set(cur["mcpServers"]) == {"other", "paper-repro"}
    assert (home / ".claude" / "skills" / "paper-repro" / "SKILL.md").read_text() == skill_text()
    assert (home / ".codex" / "skills" / "paper-repro" / "SKILL.md").exists()
    backups = [p.name for p in home.rglob("*.bak-paper-repro-*")]
    assert len(backups) == 2  # config.toml and mcp.json existed, so both were backed up

    again = run_setup(apply=True, home=home, which=which)
    assert not any(a["needed"] for a in again["actions"])
    assert (home / ".codex" / "config.toml").read_text().count("[mcp_servers.paper-repro]") == 1
    assert log.read_text().count("mcp add") == 1


def test_nothing_detected(tmp_path):
    out = run_setup(apply=True, home=tmp_path / "empty", which=lambda _: None)
    assert out["detected"] == {"claude-code": False, "codex": False, "cursor": False}
    assert out["actions"] == []


def test_project_mcp_json(tmp_path):
    home = tmp_path / "h"
    (home / ".claude").mkdir(parents=True)
    proj = tmp_path / "proj"
    proj.mkdir()
    run_setup(apply=True, home=home, which=lambda _: None, project_dir=proj)
    data = json.loads((proj / ".mcp.json").read_text())
    assert data["mcpServers"]["paper-repro"]["args"] == ["paper-repro", "mcp"]


def test_skill_frontmatter():
    text = skill_text()
    assert text.startswith("---\nname: paper-repro\ndescription: ")
    assert os.linesep not in ("\r\n",) or "\r" not in text
