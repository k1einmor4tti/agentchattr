import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge import DshBridge, DshError, room_prompt


def event(kind, data, seq=0):
    return {"event": {"type": kind, "seq": seq, "data": data}}


class Host(DshBridge):
    def __init__(self, folder):
        super().__init__("http://127.0.0.1:3080", Path(folder) / "state.json", folder)
        self.calls = []
        self.title = None
        self.running = False
        self.finish = True
        self.reads = 0

    def rpc(self, method, payload, rpc_id=None):
        self.calls.append((method, payload, rpc_id))
        if method == "session.create":
            return {"sessionId": "session-owned"}
        if method == "session.rename":
            self.title = payload["title"]
            return {"title": self.title, "seq": 0}
        if method == "session.list":
            return {"items": [{"sessionId": "session-owned", "running": self.running,
                               "projections": {"values": {"title": self.title}}}]}
        if method == "session.prompt":
            self.request = rpc_id
            self.reads = 0
            return {"accepted": True}
        if method == "session.history":
            self.reads += 1
            events = [event("turn/start", {"turn": 2}),
                      event("user/message", {"source": {"rpcId": self.request}}),
                      event("assistant/message", {"turn": 2, "message": {
                          "content": [{"type": "text", "text": "intermediate"}]}})]
            if self.reads > 1 and self.finish:
                events += [event("assistant/message", {"turn": 2, "message": {
                    "content": [{"type": "text", "text": "final answer"}]}}),
                           event("turn/end", {"turn": 2, "reason": {"kind": "completed"}})]
            return {"events": events}
        raise AssertionError(method)


class DshBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = Host(self.temp.name)
        sleep = patch("dsh_bridge.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_waits_for_final_turn_not_intermediate_text(self):
        self.assertEqual(self.host.ask("#general", "hello"), "final answer")
        self.assertEqual(self.host.reads, 2)
        methods = [c[0] for c in self.host.calls]
        self.assertEqual(methods.count("session.prompt"), 1)
        self.assertFalse(any("approval" in m or "permission" in m for m in methods))

    def test_scope_and_restart_keep_named_session_identity(self):
        row, _ = self.host.session("#one / review-7")
        self.assertEqual(row["title"], self.host.title)
        self.host.state = json.loads(self.host.path.read_text())
        same, _ = self.host.session("#one / review-7")
        self.assertEqual(same["session_id"], row["session_id"])
        self.host.session("#two")
        self.assertEqual(sum(c[0] == "session.create" for c in self.host.calls), 2)
        self.assertEqual(len(self.host.state), 2)
        self.assertEqual(self.host.path.stat().st_mode & 0o777, 0o600)

    def test_busy_session_does_not_queue_or_steer(self):
        self.host.running = True
        with self.assertRaisesRegex(DshError, "busy"):
            self.host.ask("#general", "hello")
        self.assertFalse(any(c[0] == "session.prompt" for c in self.host.calls))

    def test_timeout_retains_request_and_retry_waits_without_resubmission(self):
        with patch("dsh_bridge.time.monotonic", side_effect=[0, 1000]):
            with self.assertRaisesRegex(DshError, "pending"):
                self.host.ask("#general", "hello")
        self.host.state = json.loads(self.host.path.read_text())
        self.assertIn("pending", next(iter(self.host.state.values())))
        self.assertEqual(self.host.ask("#general", "hello"), "final answer")
        self.assertEqual(sum(c[0] == "session.prompt" for c in self.host.calls), 1)

    def test_wrong_request_and_other_turn_are_not_a_reply(self):
        row, _ = self.host.session("#test")
        row["pending"] = {"rpc_id": "ours", "digest": "unused"}
        history = {"events": [event("turn/start", {"turn": 3}),
                               event("user/message", {"source": {"rpcId": "someone-else"}}),
                               event("assistant/message", {"turn": 3, "message": {
                                   "content": [{"type": "text", "text": "wrong"}]}}),
                               event("turn/end", {"turn": 3, "reason": {"kind": "completed"}})]}
        with patch.object(self.host, "rpc", return_value=history), \
                patch("dsh_bridge.time.monotonic", side_effect=[0, 1, 1000]):
            with self.assertRaisesRegex(DshError, "pending"):
                self.host.wait(row)

    def test_failed_turn_is_not_reported_as_success(self):
        row, _ = self.host.session("#test")
        row["pending"] = {"rpc_id": "ours", "digest": "unused", "turn": 5}
        with patch.object(self.host, "rpc", return_value={"events": [
            event("turn/end", {"turn": 5, "reason": {"kind": "error"}})]}):
            with self.assertRaisesRegex(DshError, "error"):
                self.host.wait(row)
        self.assertNotIn("pending", row)

    def test_rename_failure_keeps_exact_created_session(self):
        original = self.host.rpc
        def rpc(method, *args):
            if method == "session.rename":
                raise DshError("rename failed")
            return original(method, *args)
        with patch.object(self.host, "rpc", side_effect=rpc):
            with self.assertRaises(DshError):
                self.host.session("#test")
        self.host.state = json.loads(self.host.path.read_text())
        self.host.session("#test")
        self.assertEqual(sum(c[0] == "session.create" for c in self.host.calls), 1)

    def test_rejects_remote_origins_credentials_and_paths(self):
        for url in ["https://example.com", "http://192.168.1.2:3080",
                    "http://user:secret@localhost:3080", "http://localhost:3080/api",
                    "http://localhost:3080/?token=private"]:
            with self.subTest(url=url), self.assertRaises(DshError):
                DshBridge(url, self.host.path, self.temp.name)

    def test_prompt_explains_transport_and_preserves_phase(self):
        prompt = room_prompt([{"role": "user", "content": "test"}], "review this design")
        self.assertIn("review this design", prompt)
        self.assertIn("no agentchattr MCP tools", prompt)
        self.assertIn("normal DSH permissions", prompt)

    def test_session_engine_delivers_unique_review_ids_and_phase_to_real_queue(self):
        from agents import AgentTrigger
        from registry import RuntimeRegistry
        from session_engine import SessionEngine
        from session_store import SessionStore
        from store import MessageStore
        root = Path(self.temp.name)
        registry = RuntimeRegistry(root)
        registry.seed({"dsh": {"label": "DSH"}})
        name = registry.register("dsh")["name"]
        sessions = SessionStore(str(root / "runs.json"))
        sessions.save_custom_template({"id": "smoke", "name": "Smoke", "roles": ["reviewer"],
            "phases": [{"name": "Review", "participants": ["reviewer"], "prompt": "Check only"}]})
        engine = SessionEngine(sessions, MessageStore(str(root / "messages.jsonl")),
                               AgentTrigger(registry, root), registry)
        for expected in (1, 2):
            engine.start_session("smoke", "general", {"reviewer": name}, "user", goal="DSH smoke")
            engine.end_session(expected, "test finished")
        queued = [json.loads(line) for line in (root / f"{name}_queue.jsonl").read_text().splitlines()]
        self.assertEqual([item["session_id"] for item in queued], [1, 2])
        self.assertIn("Check only", queued[0]["prompt"])


if __name__ == "__main__":
    unittest.main()
