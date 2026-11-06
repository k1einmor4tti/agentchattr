import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import room


class RoomLauncherTests(unittest.TestCase):
    def test_outer_terminals_use_a_separate_tmux_server(self):
        with patch.object(room.subprocess, "run") as call:
            room.tmux("list-sessions")
        self.assertEqual(call.call_args.args[0],
                         ["tmux", "-L", "agentchattr-room", "list-sessions"])

    def test_agent_commands_keep_approvals_and_literal_project_path(self):
        cwd = Path("/tmp/project with spaces; $(not-a-command)")
        claude = room.agent_args("claude", cwd)
        codex = room.agent_args("codex", cwd)
        self.assertIn(str(cwd), claude)
        self.assertEqual(claude[-2:], ["--permission-mode", "default"])
        self.assertEqual(codex[-4:], ["--sandbox", "workspace-write", "--ask-for-approval", "untrusted"])
        self.assertEqual(room.agent_args("codex", cwd, "account-model")[-2:],
                         ["--model", "account-model"])
        dsh = room.agent_args("dsh", cwd)
        self.assertEqual(dsh[1:], [str(ROOT / "wrapper_api.py"), "dsh", "--cwd", str(cwd)])

    def test_launch_quotes_shell_metacharacters_without_interpolation(self):
        import shlex
        argv = ["/tmp/python with spaces", "literal;$(touch example)"]
        with patch.object(room, "tmux") as call:
            room.launch("room-test", argv, Path("/tmp"))
        command = call.call_args.args[-1]
        self.assertEqual(shlex.split(command), ["env", "-u", "TMUX", *argv])

    def test_stop_only_recorded_sessions_and_retains_history(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "room-launcher.json"
            history = Path(folder) / "history.jsonl"
            state.write_text("{}")
            history.write_text("chat")
            with patch.object(room, "STATE", state), patch.object(room, "tmux") as call:
                room.stop({"sessions": ["agentchattr-room-server", "agentchattr-room-claude"]})
            self.assertEqual([c.args for c in call.call_args_list], [
                ("kill-session", "-t", "=agentchattr-room-claude"),
                ("kill-session", "-t", "=agentchattr-room-server"),
            ])
            self.assertFalse(state.exists())
            self.assertEqual(history.read_text(), "chat")

    def test_inner_agent_stop_uses_default_server(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(room, "STATE", Path(folder) / "state"), \
                patch.object(room.subprocess, "run") as call:
            room.stop({"sessions": ["agentchattr-codex-2"]})
        self.assertEqual(call.call_args.args[0],
                         ["tmux", "kill-session", "-t", "=agentchattr-codex-2"])

    def test_occupied_port_does_not_start_or_stop_any_sessions(self):
        import socket
        with tempfile.TemporaryDirectory() as folder, socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            with patch.object(room, "STATE", Path(folder) / "state"), \
                    patch.object(room, "PORTS", (port,)), \
                    patch.object(room, "tmux") as call:
                with self.assertRaisesRegex(RuntimeError, "in use"):
                    room.start([], Path(folder))
                call.assert_not_called()

    def test_wrapper_rejects_missing_cwd_before_registering(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([
                sys.executable, str(ROOT / "wrapper.py"), "claude",
                "--cwd", str(Path(folder) / "missing"),
            ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("working directory does not exist", result.stderr)
        self.assertNotIn("Registration failed", result.stdout)
