"""pi -p 驱动的 Agent 封装：调用 headless pi，解析尾部 JSON 决策。"""
import json
import os
import shutil
import subprocess


def _resolve_node():
    node = shutil.which("node")
    if node:
        return node
    for cand in (r"C:\nvm4w\nodejs\node.exe", r"C:\Program Files\nodejs\node.exe"):
        if os.path.exists(cand):
            return cand
    return "node"


def _resolve_cli():
    known = os.path.expandvars(
        r"%APPDATA%\npm\node_modules\@mariozechner\pi-coding-agent\dist\cli.js"
    )
    if os.path.exists(known):
        return known
    return None


MEMBER_CODE = """【参会成员守则】（针对非发起方：表态/提反对/提补充）
1. 以问题和诉求为主：说清问题（现状哪里不对）、诉求（我方需要/不能接受什么）；解决方案只需简要说明方向即可，不要替发起方写完整方案或代码。
2. 简明扼要：一句话能说清不用一段；禁止车轱辘话、重复已定内容、堆砌背景。
3. 就事论事：只对提案本身表态，只说自己项目的约束边界，不替别的项目做决定；领域否决要给出"不能接受的具体点"。
4. 表态边界：accept 无附加文本；reject 说清问题+诉求+不能接受的具体点；supplement 给出问题+诉求+简版方案方向。"""

CREATOR_CODE = """【发起方守则】
1. 你是提案的设计者，方案必须说详细：涉及接口/协议/数据结构/状态机变更时，必须给出代码或伪代码（签名、字段、流转、输入输出、边界行为）。
2. 发言三要素：自然说清问题（现状哪里不对）、诉求（要解决什么）、解决方案（具体怎么改，含代码/伪代码）；缺一不合格，不要机械分三段列标题。
3. 简明但完整：不堆背景、不车轱辘话；但方案本身不能含糊，要能落到可执行。"""

CHAIR_CODE = """【主持守则】
只引导不给方案；判定时归纳分歧点、以提案编号+修订号指代；决议汇编列出分工、共识、未决项。简明扼要，就事论事。"""


def extract_json(text):
    """从文本中提取最后一个合法 JSON 对象。"""
    if not text:
        return None
    dec = json.JSONDecoder()
    best = None
    for i in range(len(text)):
        if text[i] == "{":
            try:
                obj, _ = dec.raw_decode(text[i:])
                best = obj
            except json.JSONDecodeError:
                continue
    return best


def run_agent(prompt, cwd=None, timeout=300):
    """调用 headless pi，返回 (解析出的 JSON dict 或 None, 原始输出)。"""
    node = _resolve_node()
    cli = _resolve_cli()
    if not cli:
        raise RuntimeError("找不到 pi cli.js，请检查 pi 安装")
    cmd = [node, cli, "-p", prompt]
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    obj = extract_json(stdout) or extract_json(stdout + "\n" + stderr)
    return obj, stdout


def decision_prompt(role, state_text, schema_desc, task, code=MEMBER_CODE):
    return f"""你是 {role}。

【你的任务】
{task}

【当前状态】
{state_text}

{code}

【输出要求】
只输出一个 JSON 对象，不要任何解释、markdown 代码块以外的文字。格式：
{schema_desc}
"""
