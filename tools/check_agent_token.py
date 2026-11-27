#!/usr/bin/env python
"""校验 agent 的 Keycloak token 是否满足 moot 的身份要求。

用法：
    python tools/check_agent_token.py <token>
    python tools/check_agent_token.py --file /tmp/agent.token
    python tools/check_agent_token.py <token> --aud apisix-app-moot

退出码：0 = 全部通过；1 = 有不满足项。
只解 payload（不验签）：签名由 APISIX 校验，这里只检查 claim 契约。
"""
import argparse
import base64
import json
import sys

REQUIRED = [
    ("principal_id", "R2", "项目 id 的来源；缺失会退化为 service-account-xxx"),
    ("owner_id", "R3", "项目上级（人类负责人）"),
    ("sub", "R5", "稳定的主体标识（兜底唯一性）"),
]


def decode(token):
    parts = token.strip().split(".")
    if len(parts) < 2:
        raise SystemExit("不是合法 JWT")
    s = parts[1].replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return json.loads(base64.b64decode(s))


def check(claims, aud):
    rows = []

    def add(ok, rule, detail):
        rows.append((ok, rule, detail))

    for claim, rule, why in REQUIRED:
        value = claims.get(claim)
        add(bool(value), rule, f"{claim}={value!r}" + ("" if value else f" — {why}"))

    principal = str(claims.get("principal_id") or "")
    add(not principal.startswith("service-account-"), "R2b",
        "principal_id 不应是 service-account-*（否则多个 agent 会收敛成同一项目）")

    auds = claims.get("aud") or []
    if isinstance(auds, str):
        auds = [auds]
    add(aud in auds, "R4", f"aud={auds} 需包含 {aud}")

    add(bool(claims.get("azp") or claims.get("client_id")), "R5b",
        f"azp={claims.get('azp')!r} / client_id={claims.get('client_id')!r}")

    return rows


def main():
    p = argparse.ArgumentParser(description="校验 agent token 是否满足 moot 身份要求")
    p.add_argument("token", nargs="?", help="JWT 字面量")
    p.add_argument("--file", help="从文件读取 JWT")
    p.add_argument("--aud", default="apisix-app-moot", help="期望的 audience（默认 apisix-app-moot）")
    args = p.parse_args()

    token = args.token
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            token = f.read()
    if not token:
        p.error("需要 token 或 --file")

    claims = decode(token)
    rows = check(claims, args.aud)
    for ok, rule, detail in rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {rule:4} {detail}")

    failed = [r for r in rows if not r[0]]
    print()
    if failed:
        print(f"结果：不满足 {len(failed)} 项 — moot 会拒绝据此自动注册（或注册出错误身份）")
        return 1
    print("结果：全部满足 — agent 首次调用会自动注册为该 principal 的项目")
    return 0


if __name__ == "__main__":
    sys.exit(main())
