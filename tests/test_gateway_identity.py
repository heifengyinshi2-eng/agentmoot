"""网关身份（APISIX 可信头 + HMAC 证明）单元测试。"""
import base64
import hashlib
import hmac
import json
import time

from moot import gateway_identity as gi


class Headers(dict):
    """大小写不敏感 get，模拟 http.client.HTTPMessage。"""

    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


def b64(obj):
    return base64.b64encode(json.dumps(obj).encode()).decode()


def make_proof(secret, app, sub, principal, request_id, exp):
    payload = f"{app}|{sub}|{principal}|{request_id}|{exp}".encode()
    return "v1.%d.%s" % (exp, hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest())


def headers(secret, sub="sub-1", principal="agent-alpha", claims=None, exp=None, app="moot"):
    exp = exp or int(time.time()) + 60
    h = Headers(
        {
            "X-AGW-App": app,
            "X-AGW-Request-Id": "req-1",
            "X-AGW-Proof": make_proof(secret, app, sub, principal, "req-1", exp),
            "X-Principal-Id": principal,
        }
    )
    if claims is not None:
        h["X-Access-Token"] = "h." + b64(claims) + ".s"
    return h


CFG = gi.GatewayConfig("moot", ["s3cret"])


def test_agent_identity_via_access_token():
    claims = {"sub": "sub-1", "principal_id": "agent-alpha", "owner_id": "demo",
              "preferred_username": "service-account-agent-alpha"}
    actor = gi.identity(headers("s3cret", claims=claims), CFG)
    assert actor == {"principal": "agent-alpha", "kind": "agent", "owner": "demo", "sub": "sub-1"}


def test_human_identity_via_userinfo():
    claims = {"sub": "u-1", "principal_id": "demo", "preferred_username": "demo"}
    h = headers("s3cret", sub="u-1", principal="demo")
    h["X-Userinfo"] = b64(claims)
    actor = gi.identity(h, CFG)
    assert actor["kind"] == "human"
    assert actor["principal"] == "demo"
    assert actor["owner"] == ""


def test_wrong_secret_rejected():
    assert gi.identity(headers("wrong", claims={"sub": "sub-1"}), CFG) is None


def test_app_mismatch_rejected():
    assert gi.identity(headers("s3cret", app="app-a", claims={"sub": "sub-1"}), CFG) is None


def test_expired_proof_rejected():
    old = int(time.time()) - 3600
    assert gi.identity(headers("s3cret", exp=old, claims={"sub": "sub-1"}), CFG) is None


def test_missing_proof_rejected():
    h = headers("s3cret", claims={"sub": "sub-1"})
    del h["X-AGW-Proof"]
    assert gi.identity(h, CFG) is None


def test_previous_secret_accepted():
    cfg = gi.GatewayConfig("moot", ["new", "old"])
    assert gi.identity(headers("old", claims={"sub": "sub-1"}), cfg) is not None
