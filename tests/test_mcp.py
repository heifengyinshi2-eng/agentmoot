"""MCP 端点测试：initialize / tools/list / tools/call / token 身份认证 / 错误路径。"""
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

PORT = 18100


def start_server():
    root = tempfile.mkdtemp(prefix="moot-mcp-")
    t = threading.Thread(target=serve, args=(root, "127.0.0.1", PORT), daemon=True)
    t.start()
    base = f"http://127.0.0.1:{PORT}"
    for _ in range(100):  # 轮询就绪，命中即退出
        try:
            urllib.request.urlopen(base + "/health", timeout=1)
            return base
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("moot 服务未就绪")


def rpc(base, method, params=None, rid=1, token=None):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                       "params": params or {}}).encode()
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + "/mcp", data=body, method="POST", headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=10).read().decode())


def call(base, name, arguments, rid=1, token=None):
    return rpc(base, "tools/call", {"name": name, "arguments": arguments}, rid, token)["result"]


def register(base, pid):
    """注册项目，返回身份 token。"""
    r = call(base, "moot_register_project", {"id": pid})
    assert not r["isError"], r
    return json.loads(r["content"][0]["text"])["token"]


class TestMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = start_server()

    def test_initialize(self):
        r = rpc(self.base, "initialize", {"protocolVersion": "2025-06-18",
                                          "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "moot")
        # MCP 自解释入口：最小化单行 instructions
        ins = r["result"].get("instructions")
        self.assertTrue(ins and isinstance(ins, str))
        self.assertNotIn("\n", ins)
        self.assertIn("moot_register_project", ins)
        self.assertIn("moot_help", ins)

    def test_tools_list(self):
        r = rpc(self.base, "tools/list", {})
        names = [t["name"] for t in r["result"]["tools"]]
        for n in ("moot_create_issue", "moot_review_issue", "moot_create_room",
                  "moot_submit", "moot_judge", "moot_list_pending"):
            self.assertIn(n, names)
        for t in r["result"]["tools"]:
            self.assertIn("inputSchema", t)

    def test_token_identity(self):
        # 注册发 token；身份从 token 识别，不信任自报
        tok = register(self.base, "tok_app")
        self.assertTrue(tok.startswith("moot_"))
        register(self.base, "tok_base")
        # 无 token 调 list_pending → 报错，且错误信息引导去注册
        r = call(self.base, "moot_list_pending", {})
        self.assertTrue(r["isError"])
        self.assertIn("moot_register_project", r["content"][0]["text"])
        # 带 token → 识别身份
        r = call(self.base, "moot_list_pending", {}, token=tok)
        self.assertFalse(r["isError"])
        self.assertEqual(json.loads(r["content"][0]["text"])["project"], "tok_app")

    def test_issue_flow(self):
        tok_base = register(self.base, "base_flow")
        tok_app = register(self.base, "app_flow")
        # create_issue 带 app token：creator 自动识别为 app_flow
        r = call(self.base, "moot_create_issue",
                 {"assignee": "base_flow", "title": "t", "body": "b"}, token=tok_app)
        self.assertFalse(r["isError"])
        iid = json.loads(r["content"][0]["text"])["id"]
        self.assertTrue(iid.startswith("I-"))
        issue = json.loads(call(self.base, "moot_get_issue", {"id": iid})["content"][0]["text"])
        self.assertEqual(issue["creator"], "app_flow")

        r = call(self.base, "moot_review_issue", {"id": iid, "verdict": "accepted"}, token=tok_base)
        self.assertFalse(r["isError"])
        r = call(self.base, "moot_resolve_issue", {"id": iid, "body": "done"}, token=tok_base)
        self.assertFalse(r["isError"])
        r = call(self.base, "moot_close_issue", {"id": iid}, token=tok_app)
        self.assertFalse(r["isError"])

    def test_illegal_transition_rejected(self):
        tok_base = register(self.base, "base_illegal")
        tok_app = register(self.base, "app_illegal")
        r = call(self.base, "moot_create_issue",
                 {"assignee": "base_illegal", "title": "t", "body": "b"}, token=tok_app)
        iid = json.loads(r["content"][0]["text"])["id"]
        call(self.base, "moot_review_issue", {"id": iid, "verdict": "accepted"}, token=tok_base)
        call(self.base, "moot_resolve_issue", {"id": iid, "body": "done"}, token=tok_base)
        call(self.base, "moot_close_issue", {"id": iid}, token=tok_app)
        # 已 close 的 issue 不能再次 review
        r = call(self.base, "moot_review_issue", {"id": iid, "verdict": "accepted"}, token=tok_base)
        self.assertTrue(r["isError"])
        self.assertIn("closed", r["content"][0]["text"])

    def test_room_blind_view(self):
        # 盲投投影：get_room 按 token 识别身份；get_room_full/judge 仅 chair
        tok_base = register(self.base, "base_blind")
        tok_mw = register(self.base, "mw_blind")
        register(self.base, "app_blind")
        tok_chair = register(self.base, "chair")
        r = call(self.base, "moot_create_room", {
            "title": "盲投测试", "participants": ["base_blind", "mw_blind", "app_blind"],
            "chair": "chair", "agenda": [{"title": "契约", "body": "v1 原始议题", "creator": "app_blind"}]})
        self.assertFalse(r["isError"])
        rid = json.loads(r["content"][0]["text"])["id"]
        # submit 带各自 token：author 自动识别
        for tok, body in ((tok_base, "base 主张 String"), (tok_mw, "mw 主张 Number")):
            r = call(self.base, "moot_submit",
                     {"room": rid, "proposal": "P1", "action": "supplement", "body": body}, token=tok)
            self.assertFalse(r["isError"])
        # base_blind 盲投视图：只看到自己 1 条
        bl = json.loads(call(self.base, "moot_get_room", {"id": rid}, token=tok_base)["content"][0]["text"])
        self.assertEqual([s["author"] for s in bl["proposals"][0]["statements"]], ["base_blind"])
        # 无 token 调 get_room → 报错
        self.assertTrue(call(self.base, "moot_get_room", {"id": rid})["isError"])
        # get_room_full 仅 chair；非 chair 调用报错
        self.assertTrue(call(self.base, "moot_get_room_full", {"id": rid}, token=tok_base)["isError"])
        full = json.loads(call(self.base, "moot_get_room_full", {"id": rid}, token=tok_chair)["content"][0]["text"])
        self.assertEqual(len(full["proposals"][0]["statements"]), 2)
        # judge 仅 chair
        self.assertTrue(call(self.base, "moot_judge",
                             {"room": rid, "proposal": "P1", "verdict": "continue"}, token=tok_base)["isError"])
        r = call(self.base, "moot_judge",
                 {"room": rid, "proposal": "P1", "verdict": "continue", "guidance": "请发起方整合"}, token=tok_chair)
        self.assertFalse(r["isError"])
        # 判定后当前版本公开：mw_blind 盲投视图能看到全量 2 条
        post = json.loads(call(self.base, "moot_get_room", {"id": rid}, token=tok_mw)["content"][0]["text"])
        self.assertEqual(len(post["proposals"][0]["statements"]), 2)

    def test_help_overview(self):
        r = call(self.base, "moot_help", {})
        self.assertFalse(r["isError"])
        txt = r["content"][0]["text"]
        self.assertIn("moot", txt.lower())
        self.assertIn("topic", txt)

    def test_help_topic_events(self):
        r = call(self.base, "moot_help", {"topic": "events"})
        self.assertFalse(r["isError"])
        txt = r["content"][0]["text"]
        self.assertIn("/events", txt)
        self.assertIn("预留", txt)

    def test_help_topic_room(self):
        r = call(self.base, "moot_help", {"topic": "room"})
        self.assertFalse(r["isError"])
        txt = r["content"][0]["text"]
        self.assertIn("盲投", txt)
        self.assertIn("5", txt)

    def test_help_identity(self):
        r = call(self.base, "moot_help", {"topic": "identity"})
        self.assertFalse(r["isError"])
        txt = r["content"][0]["text"]
        self.assertIn("token", txt.lower())
        self.assertIn("Bearer", txt)

    def test_help_all(self):
        r = call(self.base, "moot_help", {"all": True})
        self.assertFalse(r["isError"])
        txt = r["content"][0]["text"]
        self.assertIn("/events", txt)
        self.assertIn("盲投", txt)
        self.assertIn("Bearer", txt)

    def test_help_bad_topic(self):
        r = call(self.base, "moot_help", {"topic": "nope"})
        self.assertTrue(r["isError"])

    def test_help_no_token(self):
        # 帮助公开，不需要身份
        r = call(self.base, "moot_help", {})
        self.assertFalse(r["isError"])

    def test_unknown_tool(self):
        r = call(self.base, "moot_nope", {})
        self.assertTrue(r["isError"])

    def test_unknown_method(self):
        r = rpc(self.base, "no/such/method", {})
        self.assertIn("error", r)
        self.assertEqual(r["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
