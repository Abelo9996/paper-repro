"""Talk to the real MCP server over stdio with raw JSON-RPC (no SDK client needed)."""

import json
import os
import subprocess
import sys


def rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:
        return None
    while True:
        line = proc.stdout.readline()
        assert line, proc.stderr.read()
        data = json.loads(line)
        if data.get("id") == msg["id"]:
            return data


def test_mcp_stdio_roundtrip(good_repo, tmp_path):
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, "-m", "paper_repro", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    try:
        init = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            },
        )
        assert init["result"]["serverInfo"]["name"] == "paper-repro"
        rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        names = {t["name"] for t in tools}
        assert names == {
            "inspect_repo",
            "create_env",
            "run_command",
            "extract_metrics",
            "add_claim",
            "compare_claim",
            "add_note",
            "write_report",
            "study_status",
            "verify_evidence",
            "scan_paper",
        }
        res = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "inspect_repo", "arguments": {"source": str(good_repo)}},
            },
        )["result"]
        payload = json.loads(res["content"][0]["text"])
        assert payload["claims"][0]["id"] == "c1"
        assert "create_env" in payload["next"]  # every result says what comes next
        assert "prev" not in payload and "hash" not in payload  # no log internals
        res = rpc(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "compare_claim",
                    "arguments": {"claim_id": "nope", "measured": ["m1.1"]},
                },
            },
        )["result"]
        assert res["isError"] is True
        assert "Unknown claim" in res["content"][0]["text"]
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
