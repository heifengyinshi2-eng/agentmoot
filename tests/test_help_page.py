"""帮助页测试：/help（HTML）、/help.md、/help.json 三种形态。"""
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

PORT = 18130


def start_server():
    root = tempfile.mkdtemp(prefix="moot-help-")
    t = threading.Thread(target=serve, args=(root, "127.0.0.1", PORT), daemon=True)
    t.start()
    base = f"http://127.0.0.1:{PORT}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/health", timeout=1)
            return base
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("moot 服务未就绪")


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode()


class TestHelpPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = start_server()

    def test_html(self):
        status, ctype, body = get(self.base, "/help")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        # 自解释：必须包含接入端点、上手步骤、两条协议、工具清单
        for kw in ("接入本部署", "5 分钟上手", "moot_list_pending", "issue", "room",
                   "moot_create_issue", "moot_judge", "常见问题"):
            self.assertIn(kw, body)
        # 端点用请求 Host 推导
        self.assertIn(f"http://127.0.0.1:{PORT}/agent-api/moot/mcp", body)

    def test_html_lists_all_tools(self):
        _, _, body = get(self.base, "/help")
        # MCP 工具总数为 19，帮助页 shouldn't 漏
        self.assertEqual(body.count("<tr><td><code>moot_"), 19)

    def test_markdown(self):
        status, ctype, body = get(self.base, "/help.md")
        self.assertEqual(status, 200)
        self.assertIn("markdown", ctype)
        self.assertIn("# moot 使用与接入帮助", body)
        self.assertIn("/events", body)

    def test_json(self):
        status, ctype, body = get(self.base, "/help.json")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        data = json.loads(body)
        self.assertEqual(data["service"], "moot")
        self.assertEqual(data["mode"], "token")
        self.assertEqual(len(data["tools"]), 19)
        self.assertIn("mcp", data["endpoints"])
        self.assertIn("overview", data["topics"])

    def test_public_base_override(self):
        # APISIX/nginx 终止 TLS 后 X-Forwarded-Proto=http，链接会错；MOOT_PUBLIC_BASE 优先
        os.environ["MOOT_PUBLIC_BASE"] = "https://moot.example.com"
        try:
            _, _, body = get(self.base, "/help.json")
            data = json.loads(body)
            self.assertEqual(data["base_url"], "https://moot.example.com")
            self.assertEqual(data["endpoints"]["mcp"], "https://moot.example.com/mcp")
        finally:
            os.environ.pop("MOOT_PUBLIC_BASE", None)

    def test_html_escaping(self):
        # 恶意 Host 头不应造成 HTML 注入
        req = urllib.request.Request(f"{self.base}/help")
        req.add_header("Host", "x<script>alert(1)</script>")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
        self.assertNotIn("<script>alert(1)</script>", body)


if __name__ == "__main__":
    unittest.main()
