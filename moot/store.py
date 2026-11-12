"""moot 核心存储：append-only 事件日志 + 派生状态索引 + 状态机。仅标准库。"""
import copy
import json
import os
import secrets
import time

EVENT_LOG = "events.jsonl"
STATE_FILE = "state.json"

ISSUE_STATES = ["open", "rejected", "duplicate", "accepted", "resolved", "closed"]
ROOM_STATES = ["open", "agreed", "failed"]
PROPOSAL_STATES = ["open", "agreed", "unresolvable"]
STATEMENT_ACTIONS = ["accept", "reject", "supplement"]
MAX_ROUNDS = 5  # 提案收敛的硬轮数上限（确定性兜底）


class StoreError(Exception):
    pass


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Store:
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.state = self._load()

    # ── 持久化 ──
    def _empty(self):
        return {"projects": {}, "issues": {}, "rooms": {}, "seq": {"issue": 0, "room": 0, "event": 0}, "cursor": {}}

    def _load(self):
        sp = os.path.join(self.root, STATE_FILE)
        if os.path.exists(sp):
            with open(sp, encoding="utf-8") as f:
                return json.load(f)
        return self._empty()

    def _save(self):
        sp = os.path.join(self.root, STATE_FILE)
        tmp = sp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, sp)

    def _event(self, etype, **payload):
        self.state["seq"]["event"] = self.state["seq"]["event"] + 1
        ev = {"seq": self.state["seq"]["event"], "ts": time.time(), "iso": now_iso(), "type": etype}
        ev.update(payload)
        with open(os.path.join(self.root, EVENT_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    # ── 项目 ──
    def register_project(self, pid, name=None, superior="human"):
        if pid in self.state["projects"]:
            raise StoreError(f"project 已存在: {pid}")
        # 注册即发身份 token：agent 持 token 代表该项目，服务端从 token 识别身份
        token = "moot_" + secrets.token_hex(16)
        self.state["projects"][pid] = {"id": pid, "name": name or pid,
                                       "superior": superior, "token": token}
        self._event("project.registered", project=pid, name=name or pid, superior=superior)
        self._save()
        return self.state["projects"][pid]

    def list_projects(self):
        return list(self.state["projects"].values())

    def identify(self, token):
        """token → project id；无匹配返回 None。身份由 token 保证，不信任调用方自报。"""
        if not token:
            return None
        for pid, p in self.state["projects"].items():
            if p.get("token") == token:
                return pid
        return None

    # ── issue ──
    def create_issue(self, assignee, title, body, creator):
        if assignee not in self.state["projects"]:
            raise StoreError(f"assignee 项目不存在: {assignee}")
        self.state["seq"]["issue"] += 1
        iid = f"I-{self.state['seq']['issue']:03d}"
        issue = {
            "id": iid, "title": title, "body": body,
            "creator": creator, "assignee": assignee,
            "state": "open", "comments": [],
            "history": [{"state": "open", "reason": "", "ts": now_iso()}],
            "created_at": now_iso(),
        }
        self.state["issues"][iid] = issue
        self._event("issue.created", issue=iid, creator=creator, assignee=assignee, title=title)
        self._save()
        return issue

    def review_issue(self, iid, verdict, reason=""):
        issue = self._issue(iid)
        if issue["state"] != "open":
            raise StoreError(f"issue {iid} 当前状态 {issue['state']}，不能评审")
        if verdict not in ("accepted", "rejected", "duplicate"):
            raise StoreError(f"非法评审结论: {verdict}")
        issue["state"] = verdict
        issue["history"].append({"state": verdict, "reason": reason, "ts": now_iso()})
        self._event("issue.reviewed", issue=iid, verdict=verdict, reason=reason,
                    assignee=issue["assignee"], creator=issue["creator"])
        self._save()
        return issue

    def resolve_issue(self, iid, body=""):
        issue = self._issue(iid)
        if issue["state"] != "accepted":
            raise StoreError(f"issue {iid} 状态 {issue['state']}，不能 resolve")
        issue["state"] = "resolved"
        issue["history"].append({"state": "resolved", "reason": body, "ts": now_iso()})
        self._event("issue.resolved", issue=iid, body=body,
                    assignee=issue["assignee"], creator=issue["creator"])
        self._save()
        return issue

    def close_issue(self, iid):
        issue = self._issue(iid)
        if issue["state"] != "resolved":
            raise StoreError(f"issue {iid} 状态 {issue['state']}，不能 close")
        issue["state"] = "closed"
        issue["history"].append({"state": "closed", "reason": "", "ts": now_iso()})
        self._event("issue.closed", issue=iid,
                    assignee=issue["assignee"], creator=issue["creator"])
        self._save()
        return issue

    def comment_issue(self, iid, body, author):
        issue = self._issue(iid)
        issue["comments"].append({"author": author, "body": body, "ts": now_iso()})
        self._event("issue.commented", issue=iid, author=author, body=body,
                    assignee=issue["assignee"], creator=issue["creator"])
        self._save()
        return issue

    def _issue(self, iid):
        if iid not in self.state["issues"]:
            raise StoreError(f"issue 不存在: {iid}")
        return self.state["issues"][iid]

    # ── room ──
    def create_room(self, title, participants, chair, agenda):
        for p in participants:
            if p not in self.state["projects"]:
                raise StoreError(f"项目不存在: {p}")
        self.state["seq"]["room"] += 1
        rid = f"R-{self.state['seq']['room']:03d}"
        proposals = []
        for i, item in enumerate(agenda, 1):
            proposals.append({
                "id": f"P{i}", "title": item.get("title", f"提案{i}"),
                "body": item.get("body", ""),
                "creator": item.get("creator", participants[0]),
                "version": 1,
                "state": "open",
                "versions": [{"version": 1, "body": item.get("body", "")}],
                "statements": [],
                "judgements": [],
            })
        room = {
            "id": rid, "title": title,
            "participants": participants, "chair": chair,
            "state": "open", "created_at": now_iso(),
            "proposals": proposals,
            "resolution": None,
        }
        self.state["rooms"][rid] = room
        self._event("room.created", room=rid, title=title,
                    participants=participants, chair=chair)
        self._save()
        return room

    def submit(self, rid, pid, author, action, body=""):
        room = self._room(rid)
        prop = self._proposal(room, pid)
        if author not in room["participants"]:
            raise StoreError(f"{author} 不是参与方")
        if author == prop["creator"]:
            raise StoreError(f"{author} 是提案发起人，默认接受，无需表态")
        if action not in STATEMENT_ACTIONS:
            raise StoreError(f"非法表态: {action}")
        # 同轮去重：同一作者同一版本只能表态一次
        for s in prop["statements"]:
            if s["author"] == author and s["version"] == prop["version"]:
                raise StoreError(f"{author} 本轮已表态")
        prop["statements"].append({
            "author": author, "action": action, "body": body,
            "version": prop["version"], "ts": now_iso(),
        })
        self._event("room.submitted", room=rid, proposal=pid,
                    author=author, action=action, version=prop["version"],
                    participants=room["participants"], chair=room["chair"])
        self._save()
        # 返回盲投视图副本：屏蔽同版本其他方表态，避免 submit 返回泄露（防 anchoring）
        view = copy.deepcopy(prop)
        v = prop["version"]
        view["statements"] = [s for s in prop["statements"]
                              if s["version"] != v or s["author"] == author]
        return view

    def all_accepted(self, rid, pid):
        room = self._room(rid)
        prop = self._proposal(room, pid)
        v = prop["version"]
        # 发起人默认接受，不参与表态；其余参与方须显式 accept
        required = set(room["participants"]) - {prop["creator"]}
        got = {s["author"] for s in prop["statements"] if s["version"] == v and s["action"] == "accept"}
        return required <= got

    def judge(self, rid, pid, verdict, guidance=""):
        room = self._room(rid)
        prop = self._proposal(room, pid)
        if prop["state"] != "open":
            raise StoreError(f"提案 {pid} 已 {prop['state']}，不能判定")
        if verdict == "agree":
            if not self.all_accepted(rid, pid):
                raise StoreError("未全员接受，不能判 agree")
            prop["state"] = "agreed"
        elif verdict == "unresolvable":
            prop["state"] = "unresolvable"
        elif verdict == "continue":
            if prop["version"] >= MAX_ROUNDS:
                # 确定性兜底：达轮数上限，强制无法达成，不允许继续发散
                prop["state"] = "unresolvable"
                verdict = "unresolvable"
                guidance = (guidance + " " if guidance else "") + f"（达到轮数上限 {MAX_ROUNDS}，判无法达成）"
            # 否则保持 open，等待新版本
        else:
            raise StoreError(f"非法判定: {verdict}")
        prop["judgements"].append({"verdict": verdict, "guidance": guidance,
                                   "version": prop["version"], "ts": now_iso()})
        self._event("room.judged", room=rid, proposal=pid, verdict=verdict, guidance=guidance,
                    participants=room["participants"], chair=room["chair"])
        self._save()
        return prop

    def revise(self, rid, pid, new_body, author=None):
        room = self._room(rid)
        prop = self._proposal(room, pid)
        if prop["state"] != "open":
            raise StoreError(f"提案 {pid} 已 {prop['state']}，不能修订")
        if prop["version"] >= MAX_ROUNDS:
            raise StoreError(f"提案 {pid} 已达轮数上限 {MAX_ROUNDS}，无法继续修订")
        prop["version"] += 1
        prop["body"] = new_body
        prop["versions"].append({"version": prop["version"], "body": new_body})
        if author:
            prop["statements"].append({
                "author": author, "action": "supplement", "body": new_body,
                "version": prop["version"] - 1, "ts": now_iso(),
            })
        self._event("room.revised", room=rid, proposal=pid,
                    version=prop["version"], author=author,
                    participants=room["participants"], chair=room["chair"])
        self._save()
        return prop

    def finalize(self, rid, resolution):
        room = self._room(rid)
        if room["state"] != "open":
            raise StoreError(f"room {rid} 已 {room['state']}")
        for p in room["proposals"]:
            if p["state"] == "open":
                raise StoreError(f"提案 {p['id']} 仍未收敛，不能 finalize")
        room["resolution"] = resolution
        # 一致通过 = 无 unresolvable 提案
        has_fail = any(p["state"] == "unresolvable" for p in room["proposals"])
        room["state"] = "failed" if has_fail else "agreed"
        self._event("room.finalized", room=rid, state=room["state"],
                    participants=room["participants"], chair=room["chair"])
        self._save()
        return room

    def _room(self, rid):
        if rid not in self.state["rooms"]:
            raise StoreError(f"room 不存在: {rid}")
        return self.state["rooms"][rid]

    def room_view(self, rid, actor=None):
        """room 查看视图（并行盲投投影）。

        actor 指定且非 chair 时，屏蔽「当前版本 && 其他方」的 statements：
        后表态方看不到先表态方本轮内容（防 anchoring）。历史版本（<当前版本）
        的表态、chair 判定、本人已提交的表态均可见；当前版本已被 chair 判定
        （judgements 里有该版本）则视为公开，不屏蔽。
        actor=None 或 actor==chair 时返回全量（chair 判定 / Web UI 复盘需要）。
        """
        room = self._room(rid)
        if actor is None or actor == room["chair"]:
            return room
        view = copy.deepcopy(room)
        for p in view["proposals"]:
            v = p["version"]
            judged = {j["version"] for j in p["judgements"] if "version" in j}
            if v in judged:
                continue  # 当前版本已被 chair 判定，本轮表态公开（发起方可看全量整合修订）
            p["statements"] = [s for s in p["statements"]
                               if s["version"] != v or s["author"] == actor]
        return view

    def _proposal(self, room, pid):
        for p in room["proposals"]:
            if p["id"] == pid:
                return p
        raise StoreError(f"提案不存在: {pid}")

    # ── 通知游标 ──
    def get_cursor(self, project):
        return self.state["cursor"].get(project, 0)

    def set_cursor(self, project, seq):
        self.state["cursor"][project] = seq
        self._save()

    # ── 便捷查询 ──
    def list_pending(self, project):
        """某 project 的全部待办：
        - issues: assignee=project 且 open（待评审）/ accepted（待解决）
        - verify: creator=project 且 resolved（待验收）
        - rooms: 参与的 room 中，open 提案且本人尚未在本版本表态（发起人默认接受，跳过）
        """
        issues = self.state["issues"].values()
        todo = []
        verify = []
        for i in issues:
            if i["assignee"] == project and i["state"] == "open":
                todo.append({"id": i["id"], "title": i["title"], "action": "review"})
            elif i["assignee"] == project and i["state"] == "accepted":
                todo.append({"id": i["id"], "title": i["title"], "action": "resolve"})
            elif i["creator"] == project and i["state"] == "resolved":
                verify.append({"id": i["id"], "title": i["title"]})
        rooms = []
        for r in self.state["rooms"].values():
            if project not in r["participants"] or r["state"] != "open":
                continue
            pending = []
            for p in r["proposals"]:
                if p["state"] != "open" or p["creator"] == project:
                    continue
                v = p["version"]
                stated = any(s["author"] == project and s["version"] == v
                             for s in p["statements"])
                if not stated:
                    pending.append(p["id"])
            if pending:
                rooms.append({"room": r["id"], "title": r["title"], "proposals": pending})
        return {"project": project, "issues": todo, "verify": verify, "rooms": rooms}


def notify_targets(event):
    """事件 → 目标 project 集合（纯函数，事件自包含目标方）。"""
    etype = event["type"]
    targets = set()
    if etype.startswith("issue."):
        targets.add(event.get("assignee", ""))
        targets.add(event.get("creator", ""))
    elif etype.startswith("room."):
        targets.update(event.get("participants", []))
        targets.add(event.get("chair", ""))
    # project.registered 等无通知目标
    targets.discard("")
    return targets
