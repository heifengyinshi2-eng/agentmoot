"""HTTP 服务自测：起服务 → 跑通 issue + room 全流程 → 断言 → 关服务。

用法：python tools/serve_smoke.py
仅用标准库 urllib，验证 moot serve 服务端到端可用。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORT = 18099
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main():
    store = tempfile.mkdtemp(prefix="moot-serve-")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "bin", "moot"),
         "--store", store, "serve", "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        # 轮询 /health 直到就绪（命中即退出，带超时上限）
        ready = False
        for _ in range(60):
            try:
                _, h = call("GET", "/health")
                ready = h.get("ok") is True
            except Exception:
                pass
            if ready:
                break
            time.sleep(0.5)
        if not ready:
            print("服务未能就绪")
            print(proc.stdout.read())
            sys.exit(1)
        print("✓ 服务就绪:", call("GET", "/health")[1])

        # ── 场景 1：issue 闭环 ──
        for pid in ("base-lib", "dep-app"):
            call("POST", "/projects", {"id": pid})
        s, iss = call("POST", "/issues", {
            "assignee": "base-lib", "title": "大整数精度丢失", "body": "复现步骤…",
            "creator": "dep-app",
        })
        assert s == 200, iss
        iid = iss["id"]
        call("POST", f"/issues/{iid}/review", {"verdict": "accepted", "reason": "属实"})
        call("POST", f"/issues/{iid}/resolve", {"body": "大整数转字符串"})
        call("POST", f"/issues/{iid}/close")
        _, iss2 = call("GET", f"/issues/{iid}")
        assert iss2["state"] == "closed", iss2
        print(f"✓ issue 闭环: {iid} -> {iss2['state']}")

        # ── 场景 2：room 收敛 ──
        for pid in ("base", "mw", "app"):
            call("POST", "/projects", {"id": pid})
        s, room = call("POST", "/rooms", {
            "title": "大整数接口变更", "participants": ["base", "mw", "app"],
            "chair": "facilitator",
            "agenda": [{"title": "X 接口支持大整数", "body": "int 改 string", "creator": "base"}],
        })
        assert s == 200, room
        rid = room["id"]
        call("POST", f"/rooms/{rid}/proposals/P1/submit",
             {"author": "mw", "action": "reject", "body": "依赖 int 语义"})
        call("POST", f"/rooms/{rid}/proposals/P1/submit",
             {"author": "app", "action": "supplement", "body": "新增 string 分支"})
        call("POST", f"/rooms/{rid}/proposals/P1/judge",
             {"verdict": "continue", "guidance": "请 base 给兼容方案"})
        call("POST", f"/rooms/{rid}/proposals/P1/revise",
             {"author": "base", "new_body": "int|string 联合类型"})
        call("POST", f"/rooms/{rid}/proposals/P1/submit", {"author": "mw", "action": "accept"})
        call("POST", f"/rooms/{rid}/proposals/P1/submit", {"author": "app", "action": "accept"})
        call("POST", f"/rooms/{rid}/proposals/P1/judge", {"verdict": "agree"})
        call("POST", f"/rooms/{rid}/finalize", {"resolution": "一致通过 P1 v2"})
        _, room2 = call("GET", f"/rooms/{rid}")
        assert room2["state"] == "agreed", room2
        assert room2["proposals"][0]["state"] == "agreed", room2
        print(f"✓ room 收敛: {rid} -> {room2['state']}, 提案 -> {room2['proposals'][0]['state']}")

        # ── 场景 3：确定性兜底（非法迁移被服务层拒绝）──
        s, _ = call("POST", f"/issues/{iid}/review", {"verdict": "rejected"})
        assert s == 400, f"期望 400，实际 {s}"
        print("✓ 服务层拒绝非法迁移（closed issue 再评审 → 400）")

        print("\nSERVE SMOKE ALL PASS")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
