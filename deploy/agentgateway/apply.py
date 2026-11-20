#!/usr/bin/env python3
"""把 moot 专属的网关配置应用到 agentgateway 的**部署目录**。

设计约束：agentgateway 源码里不出现任何 moot 信息。moot 只出现在：
  - <agentgateway>/deploy/podman/runtime/<env>/  （gitignore，实际部署物）
  - Keycloak 运行时数据（通过 Admin API 幂等写入）

本脚本做四件事，全部幂等：
  1. 在 runtime/<env>/env 里补齐 MOOT_CLIENT_SECRET / AGW_PROOF_SECRET_MOOT；
  2. 把 apisix-moot.yaml 片段（替换占位符后）写入 runtime/<env>/apisix.yaml；
  3. 在 Keycloak 建/更新 apisix-moot client，并给指定 agent 加 moot-audience；
  4. 重启 agw-apisix 并等待路由生效（无 token 应 401）。

注意：agentgateway 的 `run.sh up-apisix` 会用源码重新渲染 apisix.yaml，
会覆盖第 2 步的结果；执行过 up-* 之后再跑一次本脚本即可（幂等）。

用法：
  python deploy/agentgateway/apply.py --agw-root L:/piworkspace/projects/agentgateway --env prod
  python ... --check     # 只检查，不改动；缺失则退出码 1
"""
from __future__ import annotations

import argparse
import json
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRAGMENT = HERE / "apisix-moot.yaml"
ROUTE_ID = "- id: agw-svc-moot"
CLIENT_ID = "apisix-moot"
REALM = "platform"

ENV_KEYS = {
    "MOOT_CLIENT_SECRET": 24,
    "AGW_PROOF_SECRET_MOOT": 32,
}


# ---------------------------------------------------------------- env file
def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v
    return out


def save_env(path: Path, values: dict[str, str]) -> None:
    lines = [f"{k}={v}" for k, v in values.items()]
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def ensure_secrets(env_file: Path, values: dict[str, str], dry: bool) -> list[str]:
    added = []
    for key, nbytes in ENV_KEYS.items():
        if not values.get(key):
            added.append(key)
            values[key] = secrets.token_hex(nbytes)
    if added and not dry:
        save_env(env_file, values)
    return added


# ---------------------------------------------------------------- apisix
def derive_bases(apisix_text: str) -> tuple[str, str]:
    """从渲染后的 apisix.yaml 推断 auth / app 基地址。"""
    auth = app = ""
    for line in apisix_text.splitlines():
        s = line.strip()
        if not auth and s.startswith("discovery:") and "/realms/" in s:
            auth = s.split("/realms/", 1)[0].replace("discovery:", "", 1).strip()
        if not app and s.startswith("redirect_uri:") and "://" in s:
            u = s.split("redirect_uri:", 1)[1].strip()
            parsed = urllib.parse.urlparse(u)
            if parsed.scheme and parsed.netloc:
                app = f"{parsed.scheme}://{parsed.netloc}"
        if auth and app:
            break
    if not auth or not app:
        raise SystemExit("无法从 apisix.yaml 推断 auth/app 基地址（文件未渲染？）")
    return auth, app


def render_fragment(auth_base: str, app_base: str, values: dict[str, str]) -> list[str]:
    text = FRAGMENT.read_text(encoding="utf-8")
    text = text.replace("https://auth.localtest.me:18443", auth_base)
    text = text.replace("https://app.localtest.me:18443", app_base)
    text = text.replace("__MOOT_CLIENT_SECRET__", values["MOOT_CLIENT_SECRET"])
    text = text.replace("__AGW_PROOF_SECRET_MOOT__", values["AGW_PROOF_SECRET_MOOT"])
    return text.rstrip("\n").split("\n")


def upsert_route(apisix_file: Path, block: list[str], dry: bool) -> str:
    lines = apisix_file.read_text(encoding="utf-8").split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip() == ROUTE_ID), None)
    if start is not None:
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i].startswith("  - id:") or lines[i].strip() == "#END"),
            len(lines),
        )
        # 去掉块尾空行
        while end > start and not lines[end - 1].strip():
            end -= 1
        new = lines[:start] + block + [""] + lines[end:]
        action = "updated"
    else:
        idx = next((i for i, l in enumerate(lines) if l.strip() == "#END"), len(lines))
        new = lines[:idx] + block + [""] + lines[idx:]
        action = "inserted"
    if not dry:
        apisix_file.write_bytes(("\n".join(new)).encode("utf-8"))
    return action


# ---------------------------------------------------------------- keycloak
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def http_json(method: str, url: str, data=None, token: str | None = None, form=False):
    headers = {}
    body = None
    if form:
        body = urllib.parse.urlencode(data or {}).encode()
        headers["content-type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode()
        headers["content-type"] = "application/json"
    if token:
        headers["authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except Exception:
            return e.code, raw.decode("utf-8", "replace")


def audience_mapper() -> dict:
    return {
        "name": "moot-audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.custom.audience": CLIENT_ID,
            "access.token.claim": "true",
            "id.token.claim": "false",
            "introspection.token.claim": "true",
        },
    }


def claim_mappers() -> list[dict]:
    def user_attr(name, attr, claim):
        return {
            "name": name,
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "consentRequired": False,
            "config": {
                "user.attribute": attr,
                "claim.name": claim,
                "jsonType.label": "String",
                "access.token.claim": "true",
                "id.token.claim": "true",
                "userinfo.token.claim": "true",
                "introspection.token.claim": "true",
            },
        }

    def user_prop(name, attr, claim):
        return {
            "name": name,
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-property-mapper",
            "consentRequired": False,
            "config": {
                "user.attribute": attr,
                "claim.name": claim,
                "jsonType.label": "String",
                "access.token.claim": "true",
                "id.token.claim": "true",
                "userinfo.token.claim": "true",
                "introspection.token.claim": "true",
            },
        }

    return [
        user_attr("principal_id", "employee_id", "principal_id"),
        user_prop("nickname", "username", "nickname"),
        user_prop("fullname", "firstName", "fullname"),
        audience_mapper(),
    ]


def keycloak_apply(auth_base: str, app_base: str, values: dict[str, str], agents: list[str], dry: bool):
    st, tok = http_json(
        "POST",
        f"{auth_base}/realms/master/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": values.get("KEYCLOAK_ADMIN_USERNAME", "admin"),
            "password": values["KEYCLOAK_ADMIN_PASSWORD"],
        },
        form=True,
    )
    if st != 200:
        raise SystemExit(f"Keycloak 管理员登录失败: {st} {tok}")
    token = tok["access_token"]
    R = f"{auth_base}/admin/realms/{REALM}"

    rep = {
        "clientId": CLIENT_ID,
        "name": "APISIX moot service (deployed)",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "secret": values["MOOT_CLIENT_SECRET"],
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "redirectUris": [app_base + "/svc/moot/oauth2/callback"],
        "webOrigins": [app_base],
    }
    st, clients = http_json("GET", f"{R}/clients?" + urllib.parse.urlencode({"clientId": CLIENT_ID}), token=token)
    if st != 200:
        raise SystemExit(f"查询 client 失败: {st} {clients}")
    if clients:
        cid = clients[0]["id"]
        if not dry:
            st, body = http_json("PUT", f"{R}/clients/{cid}", {**clients[0], **rep}, token=token)
            if st >= 300:
                raise SystemExit(f"更新 client 失败: {st} {body}")
        print(f"  client {CLIENT_ID}: updated")
    else:
        if dry:
            print(f"  client {CLIENT_ID}: MISSING（--check 模式不创建）")
            return
        st, body = http_json("POST", f"{R}/clients", rep, token=token)
        if st >= 300:
            raise SystemExit(f"创建 client 失败: {st} {body}")
        st, clients = http_json("GET", f"{R}/clients?" + urllib.parse.urlencode({"clientId": CLIENT_ID}), token=token)
        cid = clients[0]["id"]
        print(f"  client {CLIENT_ID}: created")

    st, mappers = http_json("GET", f"{R}/clients/{cid}/protocol-mappers/models", token=token)
    have = {m["name"] for m in mappers or []}
    for m in claim_mappers():
        if m["name"] in have:
            continue
        if not dry:
            st, body = http_json("POST", f"{R}/clients/{cid}/protocol-mappers/models", m, token=token)
            if st >= 300:
                raise SystemExit(f"创建 mapper {m['name']} 失败: {st} {body}")
        print(f"  mapper {m['name']}: added")

    for agent in agents:
        st, cs = http_json("GET", f"{R}/clients?" + urllib.parse.urlencode({"clientId": agent}), token=token)
        if st != 200 or not cs:
            print(f"  agent {agent}: 未找到，跳过")
            continue
        aid = cs[0]["id"]
        st, ms = http_json("GET", f"{R}/clients/{aid}/protocol-mappers/models", token=token)
        if "moot-audience" in {m["name"] for m in ms or []}:
            print(f"  agent {agent}: moot-audience ok")
            continue
        if not dry:
            st, body = http_json("POST", f"{R}/clients/{aid}/protocol-mappers/models", audience_mapper(), token=token)
            if st >= 300:
                raise SystemExit(f"给 {agent} 加 audience 失败: {st} {body}")
        print(f"  agent {agent}: moot-audience added")


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agw-root", default=str(HERE.parent.parent.parent / "agentgateway"),
                    help="agentgateway 仓库根目录（默认同级 agentgateway）")
    ap.add_argument("--env", default="prod", help="dev | prod（默认 prod）")
    ap.add_argument("--agents", default="agent-alpha,agent-beta",
                    help="需要能访问 moot 的 agent client，逗号分隔")
    ap.add_argument("--core-machine", default=None, help="默认 agentgateway-<env>-core")
    ap.add_argument("--no-keycloak", action="store_true")
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--check", action="store_true", help="只检查，不写任何文件/不重启")
    args = ap.parse_args()

    agw = Path(args.agw_root).resolve()
    runtime = agw / "deploy" / "podman" / "runtime" / args.env
    env_file = runtime / "env"
    apisix_file = runtime / "apisix.yaml"
    if not apisix_file.exists():
        raise SystemExit(f"找不到 {apisix_file}，先跑 agentgateway 的 up-* 渲染 runtime")

    values = load_env(env_file)
    added = ensure_secrets(env_file, values, dry=args.check)
    if added:
        print(f"secrets 生成: {', '.join(added)}" + ("（--check 未写盘）" if args.check else ""))

    apisix_text = apisix_file.read_text(encoding="utf-8")
    auth_base, app_base = derive_bases(apisix_text)
    print(f"auth={auth_base}  app={app_base}")

    block = render_fragment(auth_base, app_base, values)
    action = upsert_route(apisix_file, block, dry=args.check)
    print(f"apisix 路由 agw-svc-moot: {action}" + ("（--check 未写盘）" if args.check else ""))

    if not args.no_keycloak:
        agents = [a.strip() for a in args.agents.split(",") if a.strip()]
        keycloak_apply(auth_base, app_base, values, agents, dry=args.check)

    if args.check:
        if action != "updated":
            print("检查失败：部署目录里没有 moot 路由（需运行 apply.py 注入）")
            return 1
        return 0

    if not args.no_restart:
        machine = args.core_machine or f"agentgateway-{args.env}-core"
        import subprocess
        print(f"重启 agw-apisix @ {machine}")
        rc = subprocess.run(["podman", "--connection", machine, "restart", "agw-apisix"],
                            capture_output=True, text=True)
        if rc.returncode != 0:
            raise SystemExit(f"restart 失败: {rc.stderr.strip()}")
        url = f"{app_base}/svc/moot/health"
        code = None
        for _ in range(60):
            try:
                code = urllib.request.urlopen(url, timeout=2, context=CTX).status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception:
                code = None
            if code == 401:
                break
            time.sleep(0.5)
        print(f"探活 {url} -> {code}（期望 401）")
        if code != 401:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
