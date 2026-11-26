"""网关身份：解析 APISIX 注入的可信身份头。

支持两种部署形态：

A. agentgateway AppRegistry（新，推荐）
   头部：
     X-AGW-App:              moot
     X-AGW-Identity-Type:    human | agent
     X-AGW-Identity-Mode:    jwt | gateway-header
     X-AGW-Request-Id:       <request id>
     X-Access-Token:         <Keycloak JWT>（APISIX 校验后透传）
     X-Userinfo:             <base64 JSON>（部分流程缺失，需回退解 JWT payload）
   客户端伪造的 X-AGW-* / X-Identity-* / X-Principal-* 已在 APISIX rewrite
   阶段被剥离，因此这些头可以信任（前提：服务只经网关可达）。
   启用方式：MOOT_GATEWAY_TRUST_HEADERS=1。

B. 旧部署（per-app HMAC 证明，兼容保留）
   额外带 X-AGW-Proof / X-Principal-Id，用 MOOT_GATEWAY_PROOF_SECRET 验签。

本模块只做验证与解析，不决定业务权限。
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
    """按 claims 判定 actor 类型：agent / human（无 X-AGW-Identity-Type 时的兜底）。

    Keycloak 的 client_credentials token 带 owner_id 且 preferred_username 为
    service-account-<client>；人类用户没有 owner_id。
    """
    if not claims:
        return "human", ""
    owner = str(claims.get("owner_id") or "")
    pref = str(claims.get("preferred_username") or "")
    if owner or pref.startswith("service-account-"):
        return "agent", owner
    return "human", ""


class GatewayConfig:
    def __init__(self, app, secrets, skew=DEFAULT_SKEW, trust_headers=False):
        self.app = app
        self.secrets = [s for s in secrets if s]
        self.skew = skew
        self.trust_headers = trust_headers

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

        trust = os.environ.get("MOOT_GATEWAY_TRUST_HEADERS", "").strip().lower()
        if not trust:
            # 未显式配置时：只有没配证明密钥才默认开启可信头模式
            trust = "1" if not (read("MOOT_GATEWAY_PROOF_SECRET") or read("MOOT_GATEWAY_PROOF_SECRET_PREV")) else "0"
        return cls(
            os.environ.get("MOOT_GATEWAY_APP", "moot"),
            [read("MOOT_GATEWAY_PROOF_SECRET"), read("MOOT_GATEWAY_PROOF_SECRET_PREV")],
            int(os.environ.get("MOOT_GATEWAY_PROOF_SKEW", DEFAULT_SKEW)),
            trust in ("1", "true", "yes", "on"),
        )

    def enabled(self):
        return bool(self.secrets) or self.trust_headers

    def requires_identity(self):
        """可信头模式下，除健康检查外所有请求都必须带网关身份。"""
        return self.trust_headers and not self.secrets


def identity(headers, cfg):
    """解析网关身份。

    headers 需支持大小写不敏感 get（email.message.Message / HTTPMessage 可直接用）。
    验证失败返回 None；成功返回 {principal, kind, owner, sub, mode}。
    """
    if not cfg or not cfg.enabled():
        return None
    app = headers.get("X-AGW-App") or ""
    if app != cfg.app:
        return None

    claims = _b64_json(headers.get("X-Userinfo")) or jwt_payload(headers.get("X-Access-Token"))
    sub = str(claims.get("sub") or "")
    identity_type = (headers.get("X-AGW-Identity-Type") or "").strip().lower()

    # ── B. HMAC 证明（旧部署）──
    if cfg.secrets:
        proof = headers.get("X-AGW-Proof") or ""
        request_id = headers.get("X-AGW-Request-Id") or headers.get("X-Request-Id") or ""
        principal = headers.get("X-Principal-Id") or ""
        if not principal or not request_id:
            return None
        match = PROOF_RE.match(proof)
        if not match:
            return None
        exp = int(match.group(1))
        now = int(time.time())
        if exp < now - cfg.skew or exp > now + cfg.skew:
            return None
        kind, owner = classify(claims)
        payload = f"{app}|{sub}|{principal}|{request_id}|{exp}".encode("utf-8")
        for secret in cfg.secrets:
            want = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            if hmac.compare_digest(want, match.group(2)):
                return {"principal": principal, "kind": kind, "owner": owner, "sub": sub, "mode": "proof"}
        return None

    # ── A. 可信头（agentgateway AppRegistry）──
    if not cfg.trust_headers:
        return None
    if identity_type in ("human", "agent"):
        kind = identity_type
        owner = str(claims.get("owner_id") or "") if kind == "agent" else ""
    else:
        kind, owner = classify(claims)
    principal = (
        headers.get("X-Principal-Id")
        or str(claims.get("principal_id") or "")
        or str(claims.get("preferred_username") or "")
        or sub
    )
    if not principal:
        return None
    return {"principal": principal, "kind": kind, "owner": owner, "sub": sub, "mode": "trusted-header"}
