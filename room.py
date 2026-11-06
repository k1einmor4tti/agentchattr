"""Local Claude/Codex room launcher. Uses existing CLI logins and approvals."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "room-launcher.json"
PREFIX = "agentchattr-room-"
PORTS = (8300, 8200, 8201)


def tmux(*args, check=True):
    # The outer wrapper terminals must use another tmux server. Attaching a
    # nested session to the same server can deadlock while writing its TTY.
    return subprocess.run(["tmux", "-L", "agentchattr-room", *args], check=check,
                          capture_output=True, text=True, timeout=10)


def agent_sessions():
    result = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"],
                            capture_output=True, text=True, timeout=5)
    return set(result.stdout.splitlines())


def alive(name):
    return tmux("has-session", "-t", "=" + name, check=False).returncode == 0


def launch(name, argv, cwd):
    # Unset TMUX so the wrapper can attach its agent even inside this session.
    command = shlex.join(["env", "-u", "TMUX", *map(str, argv)])
    tmux("new-session", "-d", "-s", name, "-c", str(cwd), command)


def agent_args(agent, cwd, codex_model=None):
    args = [sys.executable, str(ROOT / "wrapper.py"), agent, "--no-restart", "--cwd", str(cwd)]
    if agent == "claude":
        return args + ["--permission-mode", "default"]
    args += ["--sandbox", "workspace-write", "--ask-for-approval", "untrusted"]
    return args + ["--model", codex_model] if codex_model else args


def stop(state):
    # Only names recorded by this launcher are stopped. Leave user sessions alone.
    for name in reversed(state.get("sessions", [])):
        if name.startswith(PREFIX):
            tmux("kill-session", "-t", "=" + name, check=False)
        else:
            subprocess.run(["tmux", "kill-session", "-t", "=" + name],
                           capture_output=True, timeout=5)
    STATE.unlink(missing_ok=True)


def start(agents, cwd, codex_model=None):
    if STATE.exists():
        raise RuntimeError("Room state exists. Run status, then stop before restarting.")
    if not cwd.is_dir():
        raise RuntimeError(f"Working directory does not exist: {cwd}")
    for command in agents:
        if not shutil.which(command):
            raise RuntimeError(f"Install and log into {command} first.")
        if any(n == f"agentchattr-{command}" or n.startswith(f"agentchattr-{command}-")
               for n in agent_sessions()):
            raise RuntimeError(f"Existing {command} wrapper found; leaving it untouched.")
    for port in PORTS:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(f"Port {port} is in use; leaving that service untouched.") from None
    from config_loader import load_config
    config = load_config(ROOT)
    if config.get("server", {}).get("host", "127.0.0.1") != "127.0.0.1":
        raise RuntimeError("This launcher requires server.host = 127.0.0.1.")
    configured = (config["server"]["port"], config["mcp"]["http_port"], config["mcp"]["sse_port"])
    if configured != PORTS or any(k.startswith("AGENTCHATTR_") for k in os.environ):
        raise RuntimeError("This launcher uses default ports/data; use upstream launchers for custom instances.")
    state = {"cwd": str(cwd), "sessions": []}
    STATE.parent.mkdir(exist_ok=True)

    def remember(name):
        state["sessions"].append(name)
        STATE.write_text(json.dumps(state, indent=2) + "\n")

    try:
        name = PREFIX + "server"
        if alive(name):
            raise RuntimeError("Existing room server found; leaving it untouched.")
        launch(name, [sys.executable, ROOT / "run.py"], ROOT)
        remember(name)
        for _ in range(60):
            if not alive(name):
                raise RuntimeError("Server exited during startup.")
            try:
                with urllib.request.urlopen("http://127.0.0.1:8300/", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Server did not become ready.")
        for agent in agents:
            wrapper = PREFIX + agent
            before = agent_sessions()
            launch(wrapper, agent_args(agent, cwd, codex_model), ROOT)
            remember(wrapper)
            # Registration may allocate a suffixed identity; record only sessions
            # that appeared during our launch, never a pre-existing session.
            for _ in range(40):
                now = agent_sessions()
                created = sorted(n for n in now - before if n.startswith(f"agentchattr-{agent}"))
                if created:
                    for session in created:
                        remember(session)
                    break
                if not alive(wrapper):
                    raise RuntimeError(f"{agent} wrapper exited during startup.")
                time.sleep(0.25)
            else:
                raise RuntimeError(f"{agent} did not start. Check its CLI installation/login.")
    except Exception:
        stop(state)
        raise
    print("Room: http://127.0.0.1:8300")
    print("Use @claude / @codex in chat. Review trust/approval prompts with:")
    for agent in agents:
        print(f"  tmux -L agentchattr-room attach -t {PREFIX}{agent}")
    print("Detach: Ctrl+B, D. Stop: .venv/bin/python room.py stop")


def main():
    import tomllib
    local = ROOT / "config.local.toml"
    preferences = tomllib.loads(local.read_text()).get("room", {}) if local.exists() else {}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "stop"))
    parser.add_argument("--agents", nargs="+", choices=("claude", "codex"), default=["claude", "codex"])
    parser.add_argument("--cwd", type=Path, default=ROOT / "data" / "workspace")
    parser.add_argument("--codex-model", default=preferences.get("codex_model"),
                        help="Optional model override for this room only")
    args = parser.parse_args()
    if not shutil.which("tmux"):
        parser.error("tmux is required (macOS: brew install tmux).")
    try:
        if args.action == "start":
            if args.cwd == ROOT / "data" / "workspace":
                args.cwd.mkdir(parents=True, exist_ok=True)
            start(list(dict.fromkeys(args.agents)), args.cwd.expanduser().resolve(), args.codex_model)
        elif STATE.exists():
            state = json.loads(STATE.read_text())
            if args.action == "stop":
                stop(state)
                print("Room stopped; chat history is retained locally.")
            else:
                for name in state["sessions"]:
                    running = alive(name) if name.startswith(PREFIX) else name in agent_sessions()
                    print(f"{name}: {'running' if running else 'stopped'}")
        else:
            print("No room managed by this launcher.")
    except (RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
