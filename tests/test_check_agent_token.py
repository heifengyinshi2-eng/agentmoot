"""agent token 契约校验脚本测试（R2/R3/R4/R5）。"""
import base64
import importlib.util
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location("check_agent_token", os.path.join(ROOT, "tools", "check_agent_token.py"))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def tok(claims):
    head = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{head}.{body}.sig"


def failures(claims, aud="apisix-app-moot"):
    return [r for r in mod.check(claims, aud) if not r[0]]


class TestCheckAgentToken(unittest.TestCase):
    def test_compliant(self):
        claims = {"principal_id": "agent-alpha", "owner_id": "demo", "sub": "u1",
                  "azp": "agent-alpha", "aud": ["apisix-app-moot"]}
        self.assertEqual(failures(claims), [])

    def test_missing_principal(self):
        claims = {"preferred_username": "service-account-agent-moot", "sub": "u1",
                  "azp": "agent-moot", "aud": "apisix-app-moot"}
        rules = [r[1] for r in failures(claims)]
        self.assertIn("R2", rules)
        self.assertIn("R3", rules)
        # aud 为字符串时也应正确处理
        self.assertNotIn("R4", rules)

    def test_service_account_principal_rejected(self):
        claims = {"principal_id": "service-account-agent-moot", "owner_id": "demo", "sub": "u1",
                  "azp": "agent-moot", "aud": ["apisix-app-moot"]}
        rules = [r[1] for r in failures(claims)]
        self.assertIn("R2b", rules)

    def test_wrong_audience(self):
        claims = {"principal_id": "agent-alpha", "owner_id": "demo", "sub": "u1",
                  "azp": "agent-alpha", "aud": ["apisix-app-a"]}
        self.assertIn("R4", [r[1] for r in failures(claims)])

    def test_decode(self):
        claims = {"principal_id": "x"}
        self.assertEqual(mod.decode(tok(claims))["principal_id"], "x")


if __name__ == "__main__":
    unittest.main()
