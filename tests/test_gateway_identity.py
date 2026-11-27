"""网关身份单元测试：可信头（agentgateway AppRegistry）与 HMAC 证明（旧部署）。"""
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
TRUST = gi.GatewayConfig("moot", [], trust_headers=True)


# ── 旧部署：HMAC 证明 ──
def test_agent_identity_via_access_token():
    claims = {"sub": "sub-1", "principal_id": "agent-alpha", "owner_id": "demo",
              "preferred_username": "service-account-agent-alpha"}
    actor = gi.identity(headers("s3cret", claims=claims), CFG)
    assert actor["principal"] == "agent-alpha"
    assert actor["kind"] == "agent"
    assert actor["owner"] == "demo"
    assert actor["sub"] == "sub-1"
    assert actor["mode"] == "proof"


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


# ── 新部署：agentgateway AppRegistry 可信头 ──
def trust_headers(identity_type, claims=None, app="moot"):
    h = Headers({"X-AGW-App": app, "X-AGW-Identity-Type": identity_type,
                 "X-AGW-Identity-Mode": "jwt", "X-AGW-Request-Id": "req-1"})
    if claims is not None:
        h["X-Access-Token"] = "h." + b64(claims) + ".s"
    return h


def test_trusted_human():
    claims = {"sub": "u-1", "principal_id": "demo", "preferred_username": "demo"}
    h = trust_headers("human", claims)
    h["X-Userinfo"] = b64(claims)
    actor = gi.identity(h, TRUST)
    assert actor["kind"] == "human"
    assert actor["principal"] == "demo"
    assert actor["mode"] == "trusted-header"


def test_trusted_agent():
    claims = {"sub": "s-2", "principal_id": "agent-moot", "owner_id": "demo",
              "preferred_username": "service-account-agent-moot"}
    actor = gi.identity(trust_headers("agent", claims), TRUST)
    assert actor["kind"] == "agent"
    assert actor["principal"] == "agent-moot"
    assert actor["owner"] == "demo"


def test_trusted_app_mismatch_rejected():
    claims = {"sub": "u-1", "principal_id": "demo"}
    assert gi.identity(trust_headers("human", claims, app="other"), TRUST) is None


def test_trusted_without_claims_rejected():
    assert gi.identity(trust_headers("human"), TRUST) is None


def test_trusted_identity_type_wins_over_claims():
    # 平台判定 human，即使 claims 带 owner_id 也按 human
    claims = {"sub": "u-1", "principal_id": "demo", "owner_id": "x"}
    actor = gi.identity(trust_headers("human", claims), TRUST)
    assert actor["kind"] == "human"


def test_trust_mode_requires_identity():
    assert TRUST.requires_identity() is True
    assert CFG.requires_identity() is False


# ── 平台 Edge 签发的“每 agent 专属 JWT”（central issuer）──
def test_central_issued_agent_token():
    """central 签发的 token：iss=central，preferred_username=principal_id，无 X-Userinfo。"""
    claims = {
        "iss": "https://central.agw.internal/oidc",
        "sub": "agent-3c17362ef9561b6d",
        "azp": "agent-3c17362ef9561b6d",
        "client_id": "agent-3c17362ef9561b6d",
        "principal_id": "agent-3c17362ef9561b6d",
        "owner_id": "demo",
        "preferred_username": "agent-3c17362ef9561b6d",
        "aud": ["apisix-app-moot"],
    }
    h = trust_headers("agent", claims)
    assert "X-Userinfo" not in h
    actor = gi.identity(h, TRUST)
    assert actor == {"principal": "agent-3c17362ef9561b6d", "kind": "agent",
                     "owner": "demo", "sub": "agent-3c17362ef9561b6d", "mode": "trusted-header"}


def test_two_agents_do_not_collapse():
    """两个不同 agent 的 central token 必须解析为不同 principal（不会收敛）。"""
    def claims(agent_id):
        return {"sub": agent_id, "principal_id": agent_id, "owner_id": "demo",
                "preferred_username": agent_id, "aud": ["apisix-app-moot"]}
    a = gi.identity(trust_headers("agent", claims("agent-a1")), TRUST)
    b = gi.identity(trust_headers("agent", claims("agent-b2")), TRUST)
    assert a["principal"] != b["principal"]
