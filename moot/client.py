"""moot HTTP 客户端：对应 moot.server 的 JSON API，供 Agent / demo 远程交互。仅标准库。

用法：
    c = MootClient("http://127.0.0.1:18080")
    c.register_project("base")
    iss = c.create_issue("base", "标题", "正文", creator="app")

所有方法名与 moot.store.Store 对齐，便于 demo 从直连 store 平滑切换到走服务。
"""
import json
import urllib.error
import urllib.request

from .store import StoreError


class MootClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    # ── 底层 ──
    def _call(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8") or "{}")
                msg = payload.get("error", f"HTTP {e.code}")
            except Exception:  # noqa: BLE001
                msg = f"HTTP {e.code}"
            raise StoreError(msg)
        except urllib.error.URLError as e:
            raise StoreError(f"无法连接 moot 服务 {self.base_url}: {e.reason}")

    def health(self):
        return self._call("GET", "/health")

    # ── 项目 ──
    def register_project(self, pid, name=None, superior="human"):
        return self._call("POST", "/projects",
                          {"id": pid, "name": name, "superior": superior})

    def list_projects(self):
        return self._call("GET", "/projects")["projects"]

    # ── issue ──
    def create_issue(self, assignee, title, body, creator=""):
        return self._call("POST", "/issues",
                          {"assignee": assignee, "title": title, "body": body, "creator": creator})

    def list_issues(self):
        return self._call("GET", "/issues")["issues"]

    def get_issue(self, iid):
        return self._call("GET", f"/issues/{iid}")

    def review_issue(self, iid, verdict, reason=""):
        return self._call("POST", f"/issues/{iid}/review", {"verdict": verdict, "reason": reason})

    def resolve_issue(self, iid, body=""):
        return self._call("POST", f"/issues/{iid}/resolve", {"body": body})

    def close_issue(self, iid):
        return self._call("POST", f"/issues/{iid}/close", {})

    def comment_issue(self, iid, body, author=""):
        return self._call("POST", f"/issues/{iid}/comment", {"body": body, "author": author})

    # ── room ──
    def create_room(self, title, participants, chair, agenda):
        return self._call("POST", "/rooms",
                          {"title": title, "participants": participants,
                           "chair": chair, "agenda": agenda})

    def list_rooms(self):
        return self._call("GET", "/rooms")["rooms"]

    def get_room(self, rid):
        return self._call("GET", f"/rooms/{rid}")

    def get_proposal(self, rid, pid):
        room = self.get_room(rid)
        for p in room["proposals"]:
            if p["id"] == pid:
                return p
        raise StoreError(f"提案不存在: {pid}")

    def submit(self, rid, pid, author, action, body=""):
        return self._call("POST", f"/rooms/{rid}/proposals/{pid}/submit",
                          {"author": author, "action": action, "body": body})

    def judge(self, rid, pid, verdict, guidance=""):
        return self._call("POST", f"/rooms/{rid}/proposals/{pid}/judge",
                          {"verdict": verdict, "guidance": guidance})

    def revise(self, rid, pid, new_body, author=None):
        return self._call("POST", f"/rooms/{rid}/proposals/{pid}/revise",
                          {"new_body": new_body, "author": author})

    def finalize(self, rid, resolution=""):
        return self._call("POST", f"/rooms/{rid}/finalize", {"resolution": resolution})

    def all_accepted(self, rid, pid):
        """本地判定全员接受（与服务端 store.all_accepted 逻辑一致）。
        仅用于 chair 提示与演示层展示；真正约束由服务端 judge 兜底。"""
        room = self.get_room(rid)
        prop = next(p for p in room["proposals"] if p["id"] == pid)
        v = prop["version"]
        required = set(room["participants"]) - {prop["creator"]}
        got = {s["author"] for s in prop["statements"]
               if s["version"] == v and s["action"] == "accept"}
        return required <= got
