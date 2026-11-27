"""帮助页测试：/help（HTML）、/help.md、/help.json 三种形态。"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error

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
        # 端点用请求 Host 推导（token 模式的 MCP 路径是 /mcp）
        self.assertIn(f"http://127.0.0.1:{PORT}/mcp", body)

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


class TestPublicHelpInGatewayMode(unittest.TestCase):
    """网关可信头模式下，帮助页应当无需登录/无需身份头即可访问。"""

    PORT = 18131

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="moot-gw-help-")
        env = dict(os.environ)
        env.update({
            "MOOT_AUTH_MODE": "gateway",
            "MOOT_GATEWAY_APP": "moot",
            "MOOT_GATEWAY_TRUST_HEADERS": "1",
        })
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "moot.server", "--host", "127.0.0.1",
             "--port", str(cls.PORT), "--store", cls.root],
            cwd=repo, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.base = f"http://127.0.0.1:{cls.PORT}"
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/healthz", timeout=1)
                return
            except Exception:
                if cls.proc.poll() is not None:
                    raise RuntimeError("gateway 模式 moot 启动失败")
                time.sleep(0.2)
        raise RuntimeError("moot 服务未就绪")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def test_help_is_public(self):
        for path in ("/help", "/help.md", "/help.json"):
            with urllib.request.urlopen(self.base + path, timeout=10) as r:
                self.assertEqual(r.status, 200, path)
                self.assertTrue(r.read())

    def test_business_paths_still_require_identity(self):
        # 公开的只有帮助页；业务路径直连（无可信头）仍须 403
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/projects", timeout=10)
        self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
