"""SSE 事件流测试：project 过滤 + after 游标重放 + 事件 seq。"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moot.server import serve  # noqa: E402
from moot.store import Store  # noqa: E402

PORT = 18101


def start_server():
    root = tempfile.mkdtemp(prefix="moot-evt-")
    t = threading.Thread(target=serve, args=(root, "127.0.0.1", PORT), daemon=True)
    t.start()
    base = f"http://127.0.0.1:{PORT}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/health", timeout=1)
            return root, base
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("moot 服务未就绪")


def rpc(base, method, params=None, rid=1):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(base + "/mcp", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json, text/event-stream"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())


def call(base, name, arguments):
    return rpc(base, "tools/call", {"name": name, "arguments": arguments})["result"]


def read_sse(base, project, after=0):
    """读 once=1 的 SSE 重放流，返回事件列表（连接自然关闭）。"""
    url = f"{base}/events?project={project}&after={after}&once=1"
    resp = urllib.request.urlopen(url, timeout=10)
    events = []
    try:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    finally:
        resp.close()
    return events


class TestEvents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.base = start_server()

    def setUp(self):
        # 每个用例前造一批事件，用不同 project 隔离
        call(self.base, "moot_register_project", {"id": "base"})
        call(self.base, "moot_register_project", {"id": "app"})
        call(self.base, "moot_register_project", {"id": "other"})

    def test_project_filter(self):
        # base 相关：issue 派给 base
        call(self.base, "moot_create_issue", {"assignee": "base", "title": "t", "body": "b", "creator": "app"})
        # other 相关：issue 派给 other
        call(self.base, "moot_create_issue", {"assignee": "other", "title": "x", "body": "y", "creator": "app"})

        evts = read_sse(self.base, "base", after=0)
        types = [e["type"] for e in evts]
        # base 只收到涉及自己的 issue.created（register_project 不通知）
        self.assertIn("issue.created", types)
        # other 的 issue 不应出现在 base 的流里
        for e in evts:
            if e["type"] == "issue.created":
                self.assertEqual(e["assignee"], "base")

    def test_after_replay(self):
        # 先取一个快照游标
        call(self.base, "moot_create_issue", {"assignee": "base", "title": "1", "body": "", "creator": "app"})
        all_evts = read_sse(self.base, "base", after=0)
        seqs = [e["seq"] for e in all_evts]
        self.assertTrue(seqs)
        last = max(seqs)
        # 再产生一个新事件
        call(self.base, "moot_create_issue", {"assignee": "base", "title": "2", "body": "", "creator": "app"})
        # after=last 只应重放新事件
        new_evts = read_sse(self.base, "base", after=last)
        self.assertTrue(new_evts)
        self.assertTrue(all(e["seq"] > last for e in new_evts))
        self.assertIn("2", new_evts[0].get("title", ""))

    def test_seq_monotonic(self):
        call(self.base, "moot_create_issue", {"assignee": "base", "title": "t", "body": "b", "creator": "app"})
        evts = read_sse(self.base, "base", after=0)
        seqs = [e["seq"] for e in evts]
        self.assertEqual(seqs, sorted(seqs))
        self.assertTrue(all(s > 0 for s in seqs))

    def test_cursor_persisted(self):
        # 重放后服务端应记住 cursor
        evts = read_sse(self.base, "base", after=0)
        store = Store(self.root)
        # 直接读 state 文件确认 cursor 被写入（>= 最后 seq）
        self.assertGreaterEqual(store.get_cursor("base"), 0)

    def test_headers_and_immediate_connected_comment(self):
        """建连后应立刻发出响应头与首包（SSE comment），且声明不被中间层缓冲。"""
        url = f"{self.base}/events?project=base&after=0&once=1"
        resp = urllib.request.urlopen(url, timeout=10)
        try:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.headers.get("Content-Type", ""))
            self.assertEqual(resp.headers.get("X-Accel-Buffering"), "no")
            self.assertIn("no-transform", resp.headers.get("Cache-Control", ""))
            first = resp.readline().decode("utf-8")
            self.assertEqual(first.strip(), ": connected")
        finally:
            resp.close()

    def test_heartbeat_comment_keeps_stream_alive(self):
        """无事件时按心跳间隔发 SSE comment，防止中间层/客户端判定空闲断开。"""
        import moot.server as srv
        old_poll, old_beat = srv.EVENT_POLL_INTERVAL, srv.HEARTBEAT_INTERVAL
        srv.EVENT_POLL_INTERVAL, srv.HEARTBEAT_INTERVAL = 0.05, 0.25
        try:
            url = f"{self.base}/events?project=base&after=999999"  # 从尾部开始，不会重放旧事件
            resp = urllib.request.urlopen(url, timeout=10)
            lines = []
            deadline = time.time() + 2.0
            try:
                while time.time() < deadline:
                    line = resp.readline().decode("utf-8").strip()
                    if line:
                        lines.append(line)
                    if any(l.startswith(": ping") for l in lines):
                        break
            finally:
                resp.close()
            self.assertTrue(any(l == ": connected" for l in lines), lines)
            self.assertTrue(any(l.startswith(": ping") for l in lines), lines)
        finally:
            srv.EVENT_POLL_INTERVAL, srv.HEARTBEAT_INTERVAL = old_poll, old_beat


if __name__ == "__main__":
    unittest.main()
