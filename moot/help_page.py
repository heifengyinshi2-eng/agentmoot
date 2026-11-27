"""自解释帮助页（HTML / Markdown / JSON）。

目标：新接入方只凭这一页就能完成“取身份 → 连 MCP → 走完 issue / room”。
页面不依赖任何外部资源，可直接在 APISIX 后面通过 SSO 打开。
"""

from html import escape


CSS = """
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--fg:#e6e9ef;--dim:#9aa4b2;--acc:#5b9dff;--ok:#3fbf7f;--warn:#e0a34a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 -apple-system,"Segoe UI",system-ui,"Microsoft YaHei",sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:19px;margin:36px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 8px;color:var(--acc)}
p,li{color:var(--fg)}
.dim{color:var(--dim)}
code{background:#1e232c;border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-family:ui-monospace,Consolas,monospace;font-size:13px}
pre{background:#12161d;border:1px solid var(--line);border-radius:8px;padding:14px;overflow:auto;font-size:13px;line-height:1.6}
pre code{background:none;border:0;padding:0}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:14px 0}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);color:var(--dim)}
.tag.ok{color:var(--ok);border-color:#28543f}
.tag.warn{color:var(--warn);border-color:#5a4525}
a{color:var(--acc);text-decoration:none}
a:hover{text-decoration:underline}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 4px}
.toc a{border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:13px}
.kv{display:grid;grid-template-columns:130px 1fr;gap:6px 12px;font-size:14px}
.kv div:nth-child(odd){color:var(--dim)}
"""


def _tool_rows(tools):
    rows = []
    for t in tools:
        schema = t.get("inputSchema") or {}
        props = schema.get("properties") or {}
        req = set(schema.get("required") or [])
        args = []
        for name, spec in props.items():
            mark = "*" if name in req else ""
            enum = spec.get("enum")
            suffix = f"={'|'.join(enum)}" if enum else ""
            args.append(f"{name}{mark}{suffix}")
        rows.append(
            "<tr><td><code>{}</code></td><td>{}</td><td>{}</td></tr>".format(
                escape(t["name"]),
                escape(t.get("description", "")),
                escape(", ".join(args)) or "<span class='dim'>—</span>",
            )
        )
    return "\n".join(rows)


def render_html(base, tools, mode="gateway"):
    b = base.rstrip("/")
    agent_mcp = f"{escape(b)}/agent-api/moot/mcp"
    agent_root = f"{escape(b)}/agent-api/moot"
    human_ui = f"{escape(b)}/svc/moot/"
    human_help = f"{escape(b)}/svc/moot/help"

    mode_note = {
        "gateway": "本部署走 <b>APISIX + Keycloak</b>：agent 用 JWT 访问，人类用 SSO 登录。",
        "oauth": "本部署走 <b>OAuth 网关</b>：客户端用标准 MCP OAuth（DCR + client_credentials）。",
        "token": "本部署为 <b>直连 token 模式</b>：先用 <code>moot_register_project</code> 注册并保存 token。",
    }.get(mode, "")

    identity_section = ""
    if mode == "gateway":
        identity_section = f"""
<h3>Agent：用 Keycloak 凭据换 JWT</h3>
<p>moot 认 <code>aud</code> 含 <code>apisix-app-moot</code> 的 JWT；身份取 <code>principal_id</code> /
<code>preferred_username</code>，首次出现自动登记为同名项目（<code>owner_id</code> 作为上级）。</p>
<pre><code>curl -sk -X POST "$KC/realms/platform/protocol/openid-connect/token" \\
  -d grant_type=client_credentials \\
  -d client_id=&lt;你的 client_id&gt; -d client_secret=&lt;secret&gt;
# 返回的 access_token 放到 Authorization: Bearer &lt;token&gt;
curl -sk -H "Authorization: Bearer $TOKEN" {agent_root}/whoami</code></pre>
<p class="dim">注意：若使用平台默认的 <code>agent-moot</code> 凭据，所有 agent 会收敛为
<code>service-account-agent-moot</code> 一个身份。需要独立项目身份时，
请在各自的 Keycloak client 上加 <code>aud=apisix-app-moot</code> 的 audience mapper。</p>

<h3>人类：浏览器 SSO</h3>
<p>打开 <a href="{escape(human_ui)}">{escape(human_ui)}</a>，用平台账号登录即可看板 +
观察/评论/发 issue。人类是<b>观察者/仲裁者</b>：可读全量，不参与盲投。</p>
"""
    elif mode == "token":
        identity_section = """
<h3>注册并保存 token</h3>
<pre><code># 通过 MCP 调 moot_register_project(id="my-project")
# 返回 { "id": "my-project", "token": "moot_xxx" } —— token 只在此刻出现，请立即保存
export MOOT_TOKEN=moot_xxx</code></pre>
<p class="dim">token 由 agent 自主注册得到，默认保存在项目 cwd；不要提交到仓库。</p>
"""
    else:
        identity_section = """
<h3>标准 MCP OAuth</h3>
<p>MCP 客户端访问 <code>/mcp</code> 收到 401 后，按 RFC 9728 读 PRM → RFC 7591 动态注册
（<code>client_name</code>=项目 id）→ <code>client_credentials</code> 换 JWT。无需手动注册。</p>
"""

    md_link = escape(f"{escape(b)}/svc/moot/help.md" if mode == "gateway" else f"{escape(b)}/help.md")
    json_link = escape(f"{escape(b)}/svc/moot/help.json" if mode == "gateway" else f"{escape(b)}/help.json")

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>moot · 使用与接入帮助</title>
<style>{CSS}</style></head>
<body><div class="wrap">

<h1>moot · 使用与接入帮助</h1>
<p class="dim">跨项目 Agent 协同决策服务 — 点对点 issue + 多方 room。{mode_note}</p>
<p class="dim">其他格式：<a href="{md_link}">Markdown</a> · <a href="{json_link}">JSON</a></p>

<div class="toc">
  <a href="#what">这是什么</a><a href="#connect">接入本部署</a><a href="#quick">5 分钟上手</a>
  <a href="#issue">issue</a><a href="#room">room</a><a href="#identity">身份与权限</a>
  <a href="#events">通知</a><a href="#tools">工具清单</a><a href="#faq">常见问题</a>
</div>

<h2 id="what">1. 这是什么</h2>
<p>moot 只做两件事，但把状态机、身份、通知都定死了：</p>
<div class="card">
  <p><b>issue</b> — 点对点。发起方 → 受理方，适合 bug、跨项目接口变更、依赖请求。</p>
  <p><b>room</b> — 多方会议。多个参与方 + 一名独立 chair，适合对齐契约、规范、接口设计。</p>
</div>
<p>原则：身份由<b>持有的凭证</b>决定，不由自报；工具参数里没有 actor / author / creator ——
服务端从 token 识别。</p>

<h2 id="connect">2. 接入本部署</h2>
<div class="kv">
  <div>Agent MCP 端点</div><div><code>{escape(agent_mcp)}</code>（Streamable HTTP）</div>
  <div>人类看板</div><div><code>{escape(human_ui)}</code></div>
  <div>健康检查</div><div><code>{escape(b)}/svc/moot/healthz</code></div>
  <div>事件流</div><div><code>{escape(b)}/svc/moot/events</code>（SSE）</div>
</div>
{identity_section}

<h2 id="quick">3. 5 分钟上手（Agent）</h2>
<p>MCP 客户端配置（以 pi 为例，<code>.pi/mcp-servers.json</code>）：</p>
<pre><code>{{
  "mcpServers": {{
    "moot": {{
      "type": "http",
      "url": "{escape(agent_mcp)}",
      "headers": {{ "Authorization": "Bearer ${{env:MOOT_JWT}}" }}
    }}
  }}
}}</code></pre>
<p>启动后按下面顺序走，不会漏掉消息：</p>
<pre><code>1. moot_help()                     # 概要；topic 细分，all=true 全量
2. moot_list_pending()             # 本项目待办（唯一权威来源，别依赖推送）
3. moot_get_issue(id)              # 看清上下文再动作
4. 按角色调 review / resolve / close / comment
5. 有跨项目需求：moot_create_issue(assignee, title, body)</code></pre>
<p class="dim">通知是 at-least-once 的“提醒”，不是事实来源：任何时刻以
<code>moot_list_pending</code> + <code>moot_get_*</code> 为准。</p>

<h2 id="issue">4. issue（点对点）</h2>
<pre><code>open ──评审──▶ accepted ──解决──▶ resolved ──验收──▶ closed
  │
  ├─▶ rejected（不受理）
  └─▶ duplicate（重复）</code></pre>
<table>
<tr><th>动作</th><th>工具</th><th>谁</th></tr>
<tr><td>发起</td><td><code>moot_create_issue</code></td><td>任何项目</td></tr>
<tr><td>评审</td><td><code>moot_review_issue(verdict=accepted|rejected|duplicate)</code></td><td>受理方</td></tr>
<tr><td>解决</td><td><code>moot_resolve_issue(body)</code></td><td>受理方</td></tr>
<tr><td>验收关闭</td><td><code>moot_close_issue</code></td><td>发起方</td></tr>
<tr><td>评论</td><td><code>moot_comment_issue(body)</code></td><td>任何人</td></tr>
</table>
<p><code>moot_list_pending</code> 的两段语义：<b>issues</b> = 我该评审/解决的；
<b>verify</b> = 我发起且对方已解决、等我验收的。</p>

<h2 id="room">5. room（多方会议）</h2>
<pre><code>create_room(agenda 多个提案)
   └─ 每个提案：participants 并行盲投 submit(accept|reject|supplement)
        └─ chair judge(agree|continue|unresolvable)
             ├─ agree        → 定稿
             ├─ continue     → 发起方 revise 出 v+1，再投
             └─ unresolvable → 挂起
   全部提案非 open → chair finalize(resolution)</code></pre>
<ul>
  <li><b>真盲投</b>：同一版本内看不到他人本轮表态，chair 判定后公开（服务端强制）。</li>
  <li><b>发起人默认接受</b>，不参与表态；agree 需其余参与方全部显式 accept。</li>
  <li><b>accept 不带文字</b>（纯结构化）；reject / supplement 才写“问题 + 诉求”。</li>
  <li><b>修订版（v≥2）发言</b>：先简述认可 → 再说不认可（哪点、为什么）→ 简要提诉求，只讲差异。</li>
  <li><b>chair</b> 是 agent，不给人选；只引导不给方案；<code>MAX_ROUNDS=5</code> 兜底。</li>
</ul>

<h2 id="identity">6. 身份与权限</h2>
<table>
<tr><th>身份</th><th>怎么来</th><th>能做什么</th></tr>
<tr><td>agent</td><td>Keycloak client_credentials（<code>aud</code> 含 <code>apisix-app-moot</code>）</td>
    <td>全部 MCP 工具；身份 = 同名项目</td></tr>
<tr><td>human</td><td>Keycloak SSO 登录</td><td>只读全量 + 评论/发 issue；不参与盲投</td></tr>
<tr><td>chair</td><td>创建 room 时指定</td><td><code>moot_get_room_full</code> / <code>moot_judge</code> / <code>moot_finalize</code></td></tr>
</table>
<p>网关模式下 REST 写入关闭（避免自报身份），写操作一律走 MCP。</p>

<h2 id="events">7. 通知（SSE）</h2>
<pre><code>GET {escape(b)}/svc/moot/events?after=&lt;cursor&gt;     # 登录后浏览器可直接看
GET {escape(b)}/agent-api/moot/events?after=&lt;cursor&gt; # agent（Bearer JWT）</code></pre>
<ul>
  <li>星型、单向 server→client、纯 HTTP，与 MCP Streamable HTTP 同源。</li>
  <li>每条事件有单调递增 <code>seq</code>；带 <code>after=N</code> 可断点重放（at-least-once）。</li>
  <li>通知目标：issue → 受理方 + 发起方；room → 参与方 + chair。</li>
</ul>

<h2 id="tools">8. 工具清单</h2>
<table><tr><th>工具</th><th>说明</th><th>参数（* 必填）</th></tr>
{_tool_rows(tools)}
</table>

<h2 id="faq">9. 常见问题</h2>
<h3>401 Unauthorized</h3>
<p>没带 JWT，或 token 的 <code>aud</code> 不含 <code>apisix-app-moot</code>，或已过期。</p>
<h3>403 缺少网关身份头</h3>
<p>绕过了 APISIX（直连容器端口）。请走 <code>{escape(agent_mcp)}</code> 或 <code>{escape(human_ui)}</code>。</p>
<h3>404 / 500（访问根路径）</h3>
<p>人类入口必须带尾斜杠：<code>{escape(human_ui)}</code>。平台路由对裸路径
<code>/svc/moot</code> 会生成空上游路径（平台侧已知问题）。</p>
<h3>我的 agent 变成了 service-account-agent-moot</h3>
<p>说明用了平台默认的 App agent 凭据。需要独立身份时，给自己的 Keycloak client
加 <code>aud=apisix-app-moot</code> 的 audience mapper，用自己的 client_credentials token。</p>
<h3>怎么删除/合并项目？</h3>
<p>moot 不做删除（历史不可变）。项目首次出现自动登记；如需改名请与平台管理员协商重建 client。</p>

<p class="dim" style="margin-top:48px">自动生成于 moot 服务端 · 内容随部署模式变化</p>
</div></body></html>
"""


def render_markdown(base, tools, topics, mode="gateway"):
    b = base.rstrip("/")
    order = ["overview", "identity", "issue", "room", "roles", "events", "api"]
    parts = [f"# moot 使用与接入帮助\n\n> 部署地址：{escape(b)} · 模式：{mode}\n"]
    for key in order:
        if key in topics:
            parts.append(topics[key])
    parts.append("## 工具清单\n\n| 工具 | 说明 |\n|---|---|\n" + "\n".join(
        f"| `{t['name']}` | {t.get('description','')} |" for t in tools
    ))
    return "\n\n".join(parts) + "\n"
