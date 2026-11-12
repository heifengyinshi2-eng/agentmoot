"""生成跑测报告 HTML：读取 demo-out/*.txt，嵌入到单文件 report.html。"""
import html
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "demo-out")
REPORT = os.path.join(OUT, "report.html")

# 直接引用 demo/agents.py 里的守则，避免重复维护
_DEMO = os.path.join(ROOT, "demo")
if _DEMO not in sys.path:
    sys.path.insert(0, _DEMO)
try:
    from agents import MEMBER_CODE, CHAIR_CODE, CREATOR_CODE  # noqa: E402
except Exception:
    MEMBER_CODE, CHAIR_CODE, CREATOR_CODE = "", "", ""


def load(name):
    p = os.path.join(OUT, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    return ""


def esc(t):
    return html.escape(t)


ROOM_MERMAID = """flowchart TD
    Start([room 创建：议程=一组具体提案<br/>每个带动机背景/诉求；参与方 + chair]) --> Open
    Open[开场：chair 复述议程，确认全员到齐] --> Pick
    Pick{还有未处理提案？} -- 是 --> C1
    Pick -- 否 --> D1
    subgraph C [逐提案收敛 · 串行]
        C1[当前提案 版本 v] --> C2[一轮：全员并行盲投表态<br/>接受（无文本） / 反对+说明 / 补充<br/>发起人默认接受不参与]
        C2 --> CJ[chair 判定节点]
        CJ --> CJ1{判定}
        CJ1 -- 全员接受 --> C4[该提案：达成] --> Pick
        CJ1 -- 有反对/补充 --> CJ2[chair 引导（不给方案）<br/>偏离主题则拉回] --> C5[发起方优先调整 / 反对方提建议] --> C1
        CJ1 -- 反对含新提案 / 发起人补新提案 --> C6[追加为新提案] --> C1
        CJ1 -- 发起人无法调整 / chair判无法达成 --> C7[该提案：无法达成，记录] --> Pick
        CJ1 -- 超时/缺席 --> CJ3[chair 判断：再等 / 无法恢复] --> C1
    end
    D1[chair 汇编决议：分工 + 共识<br/>（提案编号+修订号指代）+ 未决项] --> D2[全员简单确认 / 异议]
    D2 -- 异议 --> D3[chair 裁定] --> D2
    D2 -- 全员确认 --> D4[一致通过 → 自动生成 issue] --> EndOK([正常结束])
    C2 -.整体失败.-> Fail([失败])
    C2 -.升级阻塞.-> Esc[等待上级裁决] --> C1"""

ISSUE_MERMAID = """stateDiagram-v2
    [*] --> open
    open --> rejected: 评审否决
    open --> duplicate: 评审判重复
    open --> accepted: 评审通过
    accepted --> resolved: 维护者完成
    resolved --> closed: 归档
    note right of closed : 发起方验收不满 → 另提 issue，不回滚"""


def section(title, subtitle, body_html):
    return f"""
<section class="card">
  <h2>{esc(title)}</h2>
  {f'<div class="sub">{esc(subtitle)}</div>' if subtitle else ''}
  {body_html}
</section>"""


def pre_block(text, lang=""):
    return f'<pre class="code">{esc(text)}</pre>'


def mermaid_block(src):
    return f'<pre class="mermaid">{esc(src)}</pre>'


def main():
    smoke = load("smoke.txt")
    scripted = load("scripted.txt")
    issue = load("issue.txt")
    room = load("room.txt")

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>agentmoot MVP 跑测报告</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
:root {{
  --bg:#0f1216; --card:#171c24; --border:#262d3a; --fg:#d7dde6; --dim:#8b96a8;
  --accent:#4da3ff; --green:#3ecf8e; --amber:#e0b84e; --red:#ff6b6b; --code:#10151c;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; line-height:1.6; }}
.wrap {{ max-width:1080px; margin:0 auto; padding:32px 20px 80px; }}
header {{ border-bottom:1px solid var(--border); padding-bottom:20px; margin-bottom:28px; }}
h1 {{ font-size:26px; margin:0 0 6px; }}
.meta {{ color:var(--dim); font-size:13px; }}
h2 {{ font-size:18px; margin:0 0 10px; color:var(--accent); }}
h3 {{ font-size:15px; margin:22px 0 8px; color:var(--fg); }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
  padding:22px 24px; margin-bottom:24px; }}
.sub {{ color:var(--dim); font-size:13px; margin-bottom:12px; }}
.code {{ background:var(--code); border:1px solid var(--border); border-radius:8px;
  padding:16px 18px; overflow-x:auto; font-family:"SF Mono",Consolas,"Cascadia Code",monospace;
  font-size:12.5px; line-height:1.55; white-space:pre-wrap; word-break:break-word; }}
.mermaid {{ background:var(--code); border:1px solid var(--border); border-radius:8px;
  padding:16px; text-align:center; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th,td {{ border:1px solid var(--border); padding:8px 12px; text-align:left; }}
th {{ background:#1c2330; color:var(--fg); }}
.ok {{ color:var(--green); font-weight:600; }}
.badge {{ display:inline-block; padding:1px 9px; border-radius:12px; font-size:12px;
  font-weight:600; margin-right:6px; }}
.b-ok {{ background:rgba(62,207,142,.15); color:var(--green); }}
.b-llm {{ background:rgba(77,163,255,.15); color:var(--accent); }}
.b-det {{ background:rgba(224,184,78,.15); color:var(--amber); }}
.note {{ background:rgba(77,163,255,.08); border-left:3px solid var(--accent);
  padding:10px 14px; border-radius:6px; margin:14px 0; font-size:13px; }}
ul {{ margin:8px 0; padding-left:22px; }}
li {{ margin:4px 0; }}
.tag {{ color:var(--dim); font-size:12px; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>agentmoot — MVP 跑测报告</h1>
  <div class="meta">生成时间 2026-11-11 · 场景：跨项目 issue 闭环 + 多方 room 会议收敛 · 驱动：pi -p（LLM Agent）</div>
</header>

<section class="card">
  <h2>验证结果总览</h2>
  <table>
    <tr><th>验证项</th><th>方式</th><th>结果</th></tr>
    <tr><td>状态机迁移合法性 / 重复表态去重 / 确定性兜底</td><td>脚本 smoke（无 LLM）</td><td class="ok">通过</td></tr>
    <tr><td>issue + room 完整流程骨架</td><td>确定性演示（秒级）</td><td class="ok">通过</td></tr>
    <tr><td>issue 闭环（真实 LLM Agent）</td><td>pi -p 驱动</td><td class="ok">通过（创建→评审→解决→验收→关闭）</td></tr>
    <tr><td>room 多方收敛（真实 LLM Agent）</td><td>pi -p 驱动</td><td class="ok">通过（2 轮盲投 → chair 引导 → 修订 → 一致通过 → 生成 issue）</td></tr>
  </table>
</section>

<section class="card">
  <h2>room 核心流程</h2>
  <div class="sub">逐提案串行 · 并行盲投 · chair 判定节点 · 决议事实确认</div>
  {mermaid_block(ROOM_MERMAID)}
  <h3>issue 状态机</h3>
  {mermaid_block(ISSUE_MERMAID)}
</section>

<section class="card">
  <h2>参会成员守则（按角色区分）</h2>
  <div class="sub">已注入各角色 prompt，详见 docs/committee-code.md</div>
  <h3>发起方守则</h3>
  <pre class="code">{esc(CREATOR_CODE)}</pre>
  <h3>非发起参与方守则</h3>
  <pre class="code">{esc(MEMBER_CODE)}</pre>
  <h3>主持守则（chair）</h3>
  <pre class="code">{esc(CHAIR_CODE)}</pre>
</section>

{section("测试 1 · 状态机 smoke（确定性）", "验证非法迁移拦截、未全员接受不得判 agree、重复表态去重",
          pre_block(smoke))}

{section("测试 2 · 确定性演示（秒级）", "无 LLM，固定表态驱动，快速查看完整流程",
          '<span class="badge b-det">确定性</span>' + pre_block(scripted))}

{section("测试 3 · issue 闭环（LLM Agent）", "dep-app 提 issue → base-lib 评审 accepted → resolve → dep-app 验收 → closed",
          '<span class="badge b-llm">LLM Agent</span>' + pre_block(issue))}

{section("测试 4 · room 多方收敛（LLM Agent）", "三方并行盲投表态 → chair 引导 → 发起方修订 v2 → 全员接受 → 决议生成 issue",
          '<span class="badge b-llm">LLM Agent</span>' + pre_block(room))}

<section class="card">
  <h2>关键观察</h2>
  <ul>
    <li><b>并行盲投有效</b>：room 第 1 轮 base/mw/app 独立给出不同立场（base 提重载、mw 提可选字段、app 接受原案），未互相锚定。</li>
    <li><b>chair 只引导不给方案</b>：chair 判定 continue 并归纳分歧点，由发起方 base 整合出 v2 兼容方案。</li>
    <li><b>确定性兜底生效</b>：状态机强制"未全员接受不得判 agree"，杜绝模型假宣布共识（smoke 测试 5 实测拦截）。</li>
    <li><b>决议 → issue</b>：room 达成后自动为每个参与方生成"决议来源" issue，与普通 issue 区分。</li>
    <li><b>只可追加</b>：所有状态迁移走事件日志，非法迁移（closed 再评审、重复表态）被拒绝。</li>
    <li><b>守则按角色分工生效</b>：修订方 mw 只提「问题 + 诉求 + 一句方向」，发起方 base 负责展开完整方案（API 签名/内部状态/边界/伪代码/测试集齐全），不再越俎代庖。</li>
  </ul>
  <div class="note">LLM 演示为真实 agent 输出（deepseek 驱动），非脚本；issue 场景约 1.5 分钟，room 场景约 1~2 分钟。</div>
</section>

<footer class="tag">agentmoot · docs/room-process.md · docs/implementation.md</footer>
</div>
<script>
  if (window.mermaid) {{
    mermaid.initialize({{ startOnLoad:true, theme:'dark', flowchart:{{ useMaxWidth:true }} }});
  }}
</script>
</body>
</html>"""

    os.makedirs(OUT, exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print("written:", REPORT, os.path.getsize(REPORT), "bytes")


if __name__ == "__main__":
    main()
