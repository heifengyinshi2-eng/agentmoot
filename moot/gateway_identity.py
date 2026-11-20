"""网关身份：校验 APISIX 注入的可信身份头 + per-app HMAC 证明。

契约（与 agentgateway 的 D-018/D-021 对齐）：

    X-AGW-App:          moot
    X-AGW-Request-Id:   <request id>
    X-AGW-Proof:        v1.<exp>.<hex hmac-sha256(secret, app|sub|principal|request_id|exp)>
    X-Principal-Id:     <principal_id>
    X-Access-Token:     <Keycloak JWT>（APISIX 设置；客户端同名字段已被网关剥离）
    X-Userinfo:         <base64 JSON>（人类 token 有；client_credentials 走 userinfo 会 403）

本模块只做验证与解析，不决定业务权限。签名证明覆盖 app/sub/principal/request/exp，
因此客户端直连伪造上述头会失败；重放受 exp 窗口限制。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time

PROOF_RE = re.compile(r"^v1\.(\d+)\.([0-9a-f]{64})$")
DEFAULT_SKEW = 120  # 秒；APISIX 侧签发有效期为 60s，这里放宽以容忍时钟抖动


def _b64_json(raw):
    """解码 base64/base64url JSON；失败返回 {}。"""
    if not raw:
        return {}
    try:
        s = raw.replace("-", "+").replace("_", "/")
        s += "=" * (-len(s) % 4)
        parsed = json.loads(base64.b64decode(s))
        return parsed if isinstance(parsed, dict) else {}
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def jwt_payload(token):
    """不验签地取 JWT payload（签名已由 APISIX 校验；头由网关注入且客户端不可伪造）。"""
    parts = (token or "").split(".")
    if len(parts) < 2:
        return {}
    return _b64_json(parts[1])


def classify(claims):
    """判定 actor 类型：agent / human。

    Keycloak 的 client_credentials token 带 owner_id（人类 owner）且
    preferred_username 为 service-account-<client>；人类用户没有 owner_id。
    """
    if not claims:
        return "human", ""
    owner = str(claims.get("owner_id") or "")
    pref = str(claims.get("preferred_username") or "")
    if owner or pref.startswith("service-account-"):
        return "agent", owner
    return "human", ""


class GatewayConfig:
    def __init__(self, app, secrets, skew=DEFAULT_SKEW):
        self.app = app
        self.secrets = [s for s in secrets if s]
        self.skew = skew

    @classmethod
    def from_env(cls):
        def read(name):
            value = os.environ.get(name, "")
            if value:
                return value
            path = os.environ.get(name + "_FILE", "")
            if path:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read().strip()
                except OSError:
                    return ""
            return ""

        return cls(
            os.environ.get("MOOT_GATEWAY_APP", "moot"),
            [read("MOOT_GATEWAY_PROOF_SECRET"), read("MOOT_GATEWAY_PROOF_SECRET_PREV")],
            int(os.environ.get("MOOT_GATEWAY_PROOF_SKEW", DEFAULT_SKEW)),
        )

    def enabled(self):
        return bool(self.secrets)


def identity(headers, cfg):
    """解析网关身份。

    headers 需支持大小写不敏感 get（email.message.Message / HTTPMessage 可直接用）。
    验证失败返回 None；成功返回 {principal, kind, owner, sub}。
    """
    if not cfg or not cfg.enabled():
        return None
    app = headers.get("X-AGW-App") or ""
    proof = headers.get("X-AGW-Proof") or ""
    request_id = headers.get("X-AGW-Request-Id") or headers.get("X-Request-Id") or ""
    principal = headers.get("X-Principal-Id") or ""
    if app != cfg.app or not principal or not request_id:
        return None

    match = PROOF_RE.match(proof)
    if not match:
        return None
    exp = int(match.group(1))
    now = int(time.time())
    if exp < now - cfg.skew or exp > now + cfg.skew:
        return None

    claims = _b64_json(headers.get("X-Userinfo")) or jwt_payload(headers.get("X-Access-Token"))
    sub = str(claims.get("sub") or headers.get("X-Actor-Sub") or "")
    kind, owner = classify(claims)

    payload = f"{app}|{sub}|{principal}|{request_id}|{exp}".encode("utf-8")
    for secret in cfg.secrets:
        want = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        if hmac.compare_digest(want, match.group(2)):
            return {"principal": principal, "kind": kind, "owner": owner, "sub": sub}
    return None
