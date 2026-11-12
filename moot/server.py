"""moot HTTP 服务：标准库 http.server，JSON API，长期运行。

用法：
    python -m moot.server --store <dir> --host 127.0.0.1 --port 18080
    （或）moot serve --store <dir> --port 18080

所有操作走 append-only 事件日志 + 状态机，与 CLI 共用同一套 Store。
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .store import EVENT_LOG, Store, StoreError, notify_targets


class MootHandler(BaseHTTPRequestHandler):
    """每个请求一个线程；store 与 lock 由 serve() 注入，串行化访问保证并发安全。"""
    server_version = "moot/0.1"
    store = None
    lock = None

    # ── 基础 ──
    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise StoreError(f"非法 JSON body: {e}")

    def _path_parts(self):
        return [p for p in urlparse(self.path).path.split("/") if p]

    def _log_request(self, code):
        self.log_message("%s %s -> %s", self.command, self.path, code)

    # ── 入口 ──
    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        parts = self._path_parts()
        if parts and parts[0] == "mcp":
            self._handle_mcp()
            return
        if parts and parts[0] == "events" and self.command == "GET":
            self._handle_events()
            return
        if not parts and self.command == "GET":
            self._serve_ui()
            return
        try:
            with self.lock:
                method = self.command
                body = self._body() if method == "POST" else {}
                result = self._dispatch(method, parts, body)
            self._send(200, result)
        except StoreError as e:
            self._send(400, {"error": str(e)})
        except KeyError as e:
            self._send(400, {"error": f"缺少字段: {e}"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    # ── 路由 ──
    def _dispatch(self, method, parts, body):
        s = self.store
        if not parts or parts == ["health"]:
            return {"ok": True, "service": "moot", "projects": len(s.list_projects())}

        head = parts[0]

        if head == "projects":
            if method == "GET":
                return {"projects": s.list_projects()}
            if method == "POST":
                return s.register_project(body["id"], body.get("name"), body.get("superior", "human"))

        if head == "issues":
            if len(parts) == 1:
                if method == "GET":
                    assignee = None
                    qs = urlparse(self.path).query
                    for kv in qs.split("&"):
                        if kv.startswith("assignee="):
                            assignee = kv.split("=", 1)[1]
                    issues = list(s.state["issues"].values())
                    if assignee:
                        issues = [i for i in issues if i["assignee"] == assignee]
                    return {"issues": issues}
                if method == "POST":
                    return s.create_issue(body["assignee"], body["title"], body["body"],
                                          body.get("creator", "human"))
            if len(parts) == 2 and method == "GET":
                return s._issue(parts[1])
            if len(parts) == 3:
                iid, op = parts[1], parts[2]
                if op == "review":
                    return s.review_issue(iid, body["verdict"], body.get("reason", ""))
                if op == "resolve":
                    return s.resolve_issue(iid, body.get("body", ""))
                if op == "close":
                    return s.close_issue(iid)
                if op == "comment":
                    return s.comment_issue(iid, body["body"], body.get("author", "human"))

        if head == "rooms":
            if len(parts) == 1:
                if method == "GET":
                    return {"rooms": list(s.state["rooms"].values())}
                if method == "POST":
                    return s.create_room(body["title"], body["participants"],
                                         body["chair"], body["agenda"])
            if len(parts) == 2 and method == "GET":
                return s._room(parts[1])
            if len(parts) == 3 and parts[2] == "finalize":
                return s.finalize(parts[1], body.get("resolution", ""))
            if len(parts) >= 4 and parts[2] == "proposals":
                rid, pid = parts[1], parts[3]
                op = parts[4] if len(parts) > 4 else None
                if op == "submit":
                    return s.submit(rid, pid, body["author"], body["action"], body.get("body", ""))
                if op == "judge":
                    return s.judge(rid, pid, body["verdict"], body.get("guidance", ""))
                if op == "revise":
                    return s.revise(rid, pid, body["new_body"], author=body.get("author"))

        raise StoreError(f"未知路径: {method} /{'/'.join(parts)}")

    # ── MCP（JSON-RPC over Streamable HTTP）──
    def _serve_ui(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "index.html")
        try:
            with open(path, encoding="utf-8") as f:
                html = f.read().encode("utf-8")
        except OSError:
            self._send(500, {"error": "moot/ui/index.html 缺失"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _send_jsonrpc(self, req_id, result):
        self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": result})

    def _send_jsonrpc_error(self, req_id, code, message):
        self._send(200, {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": code, "message": message}})

    def _handle_mcp(self):
        try:
            body = self._body()
        except StoreError as e:
            self._send_jsonrpc_error(None, -32700, f"Parse error: {e}")
            return
        method = body.get("method")
        req_id = body.get("id")
        params = body.get("params") or {}
        try:
            if method == "initialize":
                self._send_jsonrpc(req_id, {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "moot", "version": "0.1"},
                })
            elif method == "notifications/initialized":
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif method == "tools/list":
                self._send_jsonrpc(req_id, {"tools": MCP_TOOLS})
            elif method == "tools/call":
                with self.lock:
                    result = self._mcp_call_tool(params.get("name"), params.get("arguments") or {}, self._token())
                self._send_jsonrpc(req_id, result)
            elif method == "ping":
                self._send_jsonrpc(req_id, {})
            else:
                self._send_jsonrpc_error(req_id, -32601, f"Method not found: {method}")
        except StoreError as e:
            self._send_jsonrpc_error(req_id, -32603, str(e))
        except Exception as e:  # noqa: BLE001
            self._send_jsonrpc_error(req_id, -32603, f"{type(e).__name__}: {e}")

    def _token(self):
        """从 Authorization header 提取 Bearer token（项目身份凭证）。"""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[len("Bearer "):].strip()
        return None

    def _require_chair(self, s, rid, actor):
        """校验 actor 是否为该 room 的 chair。"""
        room = s._room(rid)
        if actor != room["chair"]:
            raise StoreError(f"只有 chair（{room['chair']}）能执行此操作")

    def _mcp_call_tool(self, name, args, token=None):
        s = self.store
        actor = s.identify(token)  # 身份由 token 保证，不信任调用方自报
        try:
            with open("/tmp/moot-tool-calls.log", "a", encoding="utf-8") as _f:
                _f.write(json.dumps({"name": name, "actor": actor, "args": args}, ensure_ascii=False) + "\n")
            if name == "moot_help":
                r = _moot_help(args.get("topic"), bool(args.get("all")))
            elif name == "moot_register_project":
                r = s.register_project(args["id"], args.get("name"), args.get("superior", "human"))
            elif name == "moot_list_projects":
                r = s.list_projects()
            elif name == "moot_create_issue":
                r = s.create_issue(args["assignee"], args["title"], args["body"], actor or "human")
            elif name == "moot_list_issues":
                issues = list(s.state["issues"].values())
                if args.get("assignee"):
                    issues = [i for i in issues if i["assignee"] == args["assignee"]]
                r = issues
            elif name == "moot_get_issue":
                r = s._issue(args["id"])
            elif name == "moot_review_issue":
                r = s.review_issue(args["id"], args["verdict"], args.get("reason", ""))
            elif name == "moot_resolve_issue":
                r = s.resolve_issue(args["id"], args.get("body", ""))
            elif name == "moot_close_issue":
                r = s.close_issue(args["id"])
            elif name == "moot_comment_issue":
                r = s.comment_issue(args["id"], args["body"], actor or "human")
            elif name == "moot_create_room":
                r = s.create_room(args["title"], args["participants"], args["chair"], args["agenda"])
            elif name == "moot_list_rooms":
                r = list(s.state["rooms"].values())
            elif name == "moot_get_room":
                if not actor:
                    raise StoreError("moot_get_room 需要项目身份（Authorization: Bearer <token>）")
                r = s.room_view(args["id"], actor)
            elif name == "moot_get_room_full":
                self._require_chair(s, args["id"], actor)
                r = s._room(args["id"])
            elif name == "moot_submit":
                if not actor:
                    raise StoreError("moot_submit 需要项目身份（Authorization: Bearer <token>）")
                r = s.submit(args["room"], args["proposal"], actor, args["action"], args.get("body", ""))
            elif name == "moot_judge":
                self._require_chair(s, args["room"], actor)
                r = s.judge(args["room"], args["proposal"], args["verdict"], args.get("guidance", ""))
            elif name == "moot_revise":
                if not actor:
                    raise StoreError("moot_revise 需要项目身份（发起方 token）")
                r = s.revise(args["room"], args["proposal"], args["new_body"], author=actor)
            elif name == "moot_finalize":
                self._require_chair(s, args["room"], actor)
                r = s.finalize(args["room"], args.get("resolution", ""))
            elif name == "moot_list_pending":
                if not actor:
                    raise StoreError("moot_list_pending 需要项目身份（Authorization: Bearer <token>）")
                r = s.list_pending(actor)
            else:
                raise StoreError(f"未知工具: {name}")
            text = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, default=str)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except StoreError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}

    # ── SSE 事件流 ──
    def _read_events(self):
        path = os.path.join(self.store.root, EVENT_LOG)
        if not os.path.exists(path):
            return []
        evts = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        evts.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return evts

    def _handle_events(self):
        qs = urlparse(self.path).query
        params = {}
        for kv in qs.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = v
        project = params.get("project", "")
        once = params.get("once") == "1"
        try:
            after = int(params.get("after", self.store.get_cursor(project)))
        except (ValueError, TypeError):
            after = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(ev):
            data = json.dumps(ev, ensure_ascii=False)
            msg = f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {data}\n\n"
            self.wfile.write(msg.encode("utf-8"))
            self.wfile.flush()

        last_seq = after
        try:
            for ev in self._read_events():
                if ev["seq"] <= last_seq:
                    continue
                last_seq = ev["seq"]
                if project in notify_targets(ev):
                    emit(ev)
            if last_seq > after:
                with self.lock:
                    self.store.set_cursor(project, last_seq)
            if once:
                return
            # 实时 tail：轮询 events.jsonl 新追加的行（标准库无 inotify）
            while True:
                time.sleep(0.5)
                new = [e for e in self._read_events() if e["seq"] > last_seq]
                for ev in new:
                    last_seq = ev["seq"]
                    if project in notify_targets(ev):
                        emit(ev)
                if new:
                    with self.lock:
                        self.store.set_cursor(project, last_seq)
        except (BrokenPipeError, ConnectionResetError):
            pass  # 客户端断开


def _mt(name, description, properties, required=None):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": required or []}}


def _str(description, enum=None):
    s = {"type": "string", "description": description}
    if enum:
        s["enum"] = enum
    return s


HELP_TOPICS = {
    "overview": """moot — 跨项目 Agent 协同决策服务

两个原语：
- **issue**：点对点（发起方 → 受理方），适合 bug / 跨项目接口变更请求
- **room**：多方会议（多名参与方 + 独立 chair），适合同步达成契约/规范

身份：注册制。`moot_register_project` 注册即发 token；agent 持 `MOOT_TOKEN`，MCP header 自动带 `Authorization: Bearer <token>`，服务端从 token 识别身份——**工具参数不用再传 actor/author/project**。

角色：成员（participant）/ 发起方（creator）/ 主席（chair）。

上手：
1. `moot_list_pending` 看本项目待办（无参数）
2. issue：`moot_get_issue` / `moot_review_issue` / `moot_resolve_issue`
3. room：`moot_get_room` 看提案，`moot_submit` 表态

渐进披露：`moot_help(topic="issue"|"room"|"identity"|"events"|"roles"|"api")` 看细节；`moot_help(all=true)` 一次全量。""",
    "issue": """## issue（点对点）

状态机：
- open → accepted → resolved → closed（受理方评审 → 解决，发起方验收关闭）
- open → rejected（不受理），open → duplicate（重复）

工具：
- `moot_create_issue(assignee, title, body)`：creator 自动为当前项目
- `moot_review_issue(id, verdict, reason)`：verdict ∈ accepted/rejected/duplicate（受理方）
- `moot_resolve_issue(id, body)`：受理方交付方案
- `moot_close_issue(id)`：发起方验收
- `moot_comment_issue(id, body)`：追加评论（author 自动）

待办（`moot_list_pending`）：issues 段 = assignee 且 open（待评审）/ accepted（待解决）；verify 段 = creator 且 resolved（待验收）。""",
    "room": """## room（多方会议）

流程：create_room → 成员 submit 表态 → chair judge 判定 → 发起方 revise 出下一版 → … → chair finalize 汇编决议。

关键规则：
- **并行盲投**：同一版本内看不到其他方本轮表态（防 anchoring）；chair 判定该版本后公开。
- **发起人默认接受**：提案 creator 不参与表态。
- **全员接受才可 agree**：required = 参与方 − 发起人，须全部显式 accept。
- **MAX_ROUNDS = 5**：达轮数上限时 chair 判 continue 会被强制转为 unresolvable（确定性兜底）。
- 提案状态：open / agreed / unresolvable；room 状态：open / agreed / failed。
- finalize 前置：所有提案均非 open。

工具：
- `moot_create_room(title, participants, chair, agenda)`：agenda 每项 {title, body, creator}
- `moot_get_room(id)`：成员视角（盲投投影）
- `moot_get_room_full(id)`：仅 chair，全量
- `moot_submit(room, proposal, action, body)`：action ∈ accept/reject/supplement（accept 无文本）
- `moot_judge(room, proposal, verdict, guidance)`：仅 chair，verdict ∈ agree/continue/unresolvable
- `moot_revise(room, proposal, new_body)`：发起方出 v+1
- `moot_finalize(room, resolution)`：仅 chair""",
    "identity": """## identity（身份认证）

- 注册：`moot_register_project(id)` → 返回 `token`（`moot_` 前缀）。同一 id 重复注册报错。
- 携带：agent 运行时设 `MOOT_TOKEN=<token>`；pi-mcp 配 headers `Authorization: Bearer ${env:MOOT_TOKEN}`，运行时展开（密钥不落盘）。
- 识别：服务端 `identify(token)` 反查项目 id 作为操作者身份；工具参数不传 actor/author/project/creator。
- 权限：`moot_get_room_full` / `moot_judge` / `moot_finalize` 仅该 room 的 chair。
- 无 token：moot_help、list_projects、list_issues/rooms、get_issue 等公开查询可用；涉及身份的（submit/get_room/list_pending/create_issue/comment/revise）需 token。""",
    "events": """## events（SSE 事件通道）

端点：`GET /events?project=X&after=N`（Server-Sent Events）
- 事件类型：project.registered、issue.created/reviewed/resolved/closed/commented、room.created/submitted/judged/revised/finalized
- 每条事件带 seq（单调递增）；`after=N` 从游标 N 之后重放，支持断点续传
- 通知目标：issue → assignee + creator；room → participants + chair
- 语义：at-least-once（可重复、可丢）；**正确性不依赖通知**，权威状态由 `moot_list_pending` 拉取保证

现状（重要）：当前 agent 是 `pi -p` 一次性运行，**没有常驻订阅 SSE 的能力**；`/events` 是为将来常驻 agent 预留的唤醒通道。现阶段 agent 上线先无条件调一次 `moot_list_pending` 即可。""",
    "roles": """## roles（角色守则）

- **成员 / 修订方（participant）**：
  - accept = 纯结构化调用，无文本；reject/supplement 才写说明（问题 + 诉求 + 方案方向）
  - 针对修订案（v≥2）：只讲与上版的差异；先简述认可的部分（已认可且未变的不重复）→ 说明不认可的部分（哪一点、为什么）→ 简要提诉求（方向即可，不替发起方写完整方案）
- **发起方（creator）**：
  - 方案说详细（字段/接口/职责/边界），负责 revise 整合各方诉求
  - 默认接受，不参与盲投表态
- **主席（chair）**：
  - 独立第三方，只引导不给方案；用 judge 的 guidance 给方向
  - 遵守自己发出的议程要求，但不盲从自己的总结内容（可能缺业务上下文），以业务事实为准""",
    "api": """## api（工具清单）

注册/查询：moot_register_project、moot_list_projects、moot_list_issues、moot_get_issue、moot_list_rooms、moot_get_room、moot_get_room_full、moot_list_pending
issue：moot_create_issue、moot_review_issue、moot_resolve_issue、moot_close_issue、moot_comment_issue
room：moot_create_room、moot_submit、moot_judge、moot_revise、moot_finalize
帮助：moot_help(topic?, all?)

完整参数见 `tools/list`（MCP inputSchema）。""",
}


def _moot_help(topic=None, all_=False):
    if all_:
        parts = ["# moot 全量帮助"]
        parts.extend(HELP_TOPICS[t] for t in ("overview", "issue", "room", "identity", "events", "roles", "api"))
        return "\n\n".join(parts)
    t = topic or "overview"
    if t not in HELP_TOPICS:
        raise StoreError(f"未知 help 主题: {t}（可选: {', '.join(HELP_TOPICS)}）")
    return HELP_TOPICS[t]


MCP_TOOLS = [
    _mt("moot_help", "系统帮助：无参数返回概要；topic 指定主题渐进披露；all=true 一次全量",
        {"topic": _str("主题（渐进披露）", ["overview", "issue", "room", "identity", "events", "roles", "api"]),
         "all": {"type": "boolean", "description": "返回全量帮助"}}),
    _mt("moot_register_project", "注册一个项目，返回身份 token（agent 持 token 代表该项目）",
        {"id": _str("项目唯一 ID（如 base-lib/mw/app）"), "name": _str("显示名"), "superior": _str("上级/仲裁者，默认 human")}, ["id"]),
    _mt("moot_list_projects", "列出所有项目", {}),
    _mt("moot_create_issue", "创建一个 issue 派给某项目（creator 从 token 识别）",
        {"assignee": _str("受理项目 ID"), "title": _str("标题"), "body": _str("正文")}, ["assignee", "title", "body"]),
    _mt("moot_list_issues", "列出 issue（可按 assignee 过滤）", {"assignee": _str("按受理项目过滤")}),
    _mt("moot_get_issue", "查看单个 issue", {"id": _str("issue ID，如 I-001")}, ["id"]),
    _mt("moot_review_issue", "评审 issue（受理方决定）",
        {"id": _str("issue ID"), "verdict": _str("评审结论", ["accepted", "rejected", "duplicate"]), "reason": _str("理由")}, ["id", "verdict"]),
    _mt("moot_resolve_issue", "解决 issue（受理方）", {"id": _str("issue ID"), "body": _str("解决方案描述")}, ["id"]),
    _mt("moot_close_issue", "关闭 issue（验收通过后）", {"id": _str("issue ID")}, ["id"]),
    _mt("moot_comment_issue", "追加评论（author 从 token 识别）", {"id": _str("issue ID"), "body": _str("评论内容")}, ["id", "body"]),
    _mt("moot_create_room", "发起多方会议（room）",
        {"title": _str("议题标题"), "participants": {"type": "array", "items": {"type": "string"}, "description": "参与方项目 ID 列表"},
         "chair": _str("主席（独立引导，不给方案）"), "agenda": {"type": "array", "items": {"type": "object"}, "description": "提案列表，每项含 title/body/creator"}},
        ["title", "participants", "chair", "agenda"]),
    _mt("moot_list_rooms", "列出所有会议", {}),
    _mt("moot_get_room", "查看单个会议（成员视角：按 token 识别身份，盲投投影屏蔽同版本他人表态）",
        {"id": _str("room ID，如 R-001")}, ["id"]),
    _mt("moot_get_room_full", "查看单个会议全量（仅 chair，含所有参与方表态）",
        {"id": _str("room ID，如 R-001")}, ["id"]),
    _mt("moot_submit", "对提案表态（author 从 token 识别）",
        {"room": _str("room ID"), "proposal": _str("提案 ID，如 P1"),
         "action": _str("表态", ["accept", "reject", "supplement"]), "body": _str("reject/supplement 时的说明")}, ["room", "proposal", "action"]),
    _mt("moot_judge", "主席判定提案（仅 chair）",
        {"room": _str("room ID"), "proposal": _str("提案 ID"), "verdict": _str("判定", ["agree", "continue", "unresolvable"]), "guidance": _str("continue 时的引导")}, ["room", "proposal", "verdict"]),
    _mt("moot_revise", "发起方修订提案（出下一版本，author 从 token 识别）",
        {"room": _str("room ID"), "proposal": _str("提案 ID"), "new_body": _str("新版本正文")}, ["room", "proposal", "new_body"]),
    _mt("moot_finalize", "主席汇编决议，结束会议（仅 chair）", {"room": _str("room ID"), "resolution": _str("决议文本")}, ["room"]),
    _mt("moot_list_pending", "本项目的全部待办（身份从 token 识别）", {}),
]


def serve(root, host="127.0.0.1", port=18080):
    MootHandler.store = Store(root)
    MootHandler.lock = threading.RLock()
    srv = ThreadingHTTPServer((host, port), MootHandler)
    print(f"moot 服务已启动: http://{host}:{port}  (store={root})")
    print("Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        print("服务已停止")


def main():
    import argparse
    p = argparse.ArgumentParser(description="moot HTTP 服务")
    p.add_argument("--store", default=None, help="存储目录（默认 MOOT_HOME 或 ./.moot）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18080)
    args = p.parse_args()
    import os
    root = args.store or os.environ.get("MOOT_HOME") or os.path.join(os.getcwd(), ".moot")
    serve(root, args.host, args.port)


if __name__ == "__main__":
    main()
