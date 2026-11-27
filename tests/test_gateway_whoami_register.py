"""网关模式：agent 调 /whoami 即应完成「首次出现自动登记」。

背景：平台的 agent 接入第一步通常是 GET /whoami 确认身份。如果只在 MCP 工具调用时
才登记项目，那么「只调过 whoami」的 agent 在 moot 里不存在，别人给它提 issue 会报
`assignee 项目不存在`（agentgateway 实测踩到）。
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

PORT = 18132


def b64(obj):
    return base64.b64encode(json.dumps(obj).encode()).decode()


def headers(principal="agent-x", owner="owner-1", kind="agent"):
    claims = {
        "sub": f"sub-{principal}",
        "principal_id": principal,
        "owner_id": owner,
        "azp": principal,
    }
    return {
        "X-AGW-App": "moot",
        "X-AGW-Identity-Type": kind,
        "X-AGW-Identity-Mode": "jwt",
        "X-AGW-Request-Id": "req-1",
        "X-Access-Token": "h." + b64(claims) + ".s",
    }


def get(path, hdrs=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}")
    for k, v in (hdrs or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode()


class TestWhoamiAutoRegister(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="moot-whoami-")
        env = dict(os.environ)
        env.update({
            "MOOT_AUTH_MODE": "gateway",
            "MOOT_GATEWAY_APP": "moot",
            "MOOT_GATEWAY_TRUST_HEADERS": "1",
        })
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "moot.server", "--host", "127.0.0.1",
             "--port", str(PORT), "--store", cls.root],
            cwd=repo, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=1)
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

    def test_whoami_registers_agent_project(self):
        # 登记前：项目不存在
        _, body = get("/projects", headers())
        self.assertNotIn("agent-x", body)

        status, body = get("/whoami", headers())
        self.assertEqual(status, 200)
        self.assertIn('"principal": "agent-x"', body)

        # whoami 之后：项目已在，且 superior = owner_id
        _, body = get("/projects", headers())
        projects = json.loads(body)["projects"]
        self.assertIn({"id": "agent-x", "name": "agent-x", "superior": "owner-1"}, projects)

    def test_whoami_without_identity_stays_public(self):
        status, body = get("/whoami")
        self.assertEqual(status, 200)
        self.assertIn('"identified": false', body)

    def test_human_does_not_become_project(self):
        h = headers(principal="linsen", owner="", kind="human")
        get("/whoami", h)
        _, body = get("/projects", headers())
        self.assertNotIn("linsen", body)


if __name__ == "__main__":
    unittest.main()
