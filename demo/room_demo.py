"""场景 2：多方会议（room）逐提案收敛（带 Agent，走 HTTP 服务交互）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import start_server  # noqa: E402
from agents import run_agent, decision_prompt, CHAIR_CODE, CREATOR_CODE  # noqa: E402

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".moot-serve-room")
PORT = 18088
ROUNDS = 2  # 演示轮数上限（< store.MAX_ROUNDS，正常 2 轮内收敛）

PARTICIPANTS = ["base", "mw", "app"]
CHAIR = "facilitator"

ROLES = {
    "base": "基础功能维护者（维护 X 接口所在的底层库）",
    "mw": "中间件维护者（中间件依赖 X 接口的 int 语义）",
    "app": "应用集成者（最终应用，希望接口支持大整数）",
}
CHAIR_ROLE = "独立会议主持（facilitator）：不参与项目，只做引导、汇总、判定"


def log(*a):
    print(*a)


def prior_statements(prop):
    v = prop["version"]
    return [st for st in prop["statements"] if st["version"] < v]


def proposal_state_text(prop, show_current_statements):
    lines = [
        f"提案 {prop['id']}（版本 v{prop['version']}）：{prop['title']}",
        f"正文: {prop['body']}",
    ]
    sts = prop["statements"] if show_current_statements else prior_statements(prop)
    if sts:
        lines.append("历史表态：")
        for st in sts:
            lines.append(f"  - v{st['version']} {st['author']} {st['action']}: {st['body'][:120]}")
    return "\n".join(lines)


def main():
    proc, c = start_server(STORE, PORT)
    try:
        for pid in PARTICIPANTS:
            c.register_project(pid, name=ROLES[pid].split("（")[0], superior="human")

        log("=" * 70)
        log("【场景2】三方会议：base 改接口，mw/app 表态，chair 引导收敛（走 HTTP 服务）")
        log("=" * 70)

        agenda = [{
            "title": "X 接口参数从 int 改为 string 以支持大整数",
            "body": ("base 提议：把 X 接口的参数类型从 int 改为 string，避免超过 2^53 的大整数精度丢失。\n\n"
                     "签名：`void setX(string x); string getX();`\n"
                     "语义：x 为十进制整数字符串，接收方按 BigInt 解析；非数字返回 E_FORMAT，越界返回 E_RANGE。"),
            "creator": "base",
        }]
        room = c.create_room("大整数接口变更协调", PARTICIPANTS, CHAIR, agenda)
        rid = room["id"]
        log(f"\n[系统] 会议 {rid} 创建，参与方 {PARTICIPANTS}，chair={CHAIR}")

        for prop in room["proposals"]:
            log(f"\n{'─' * 60}\n处理提案 {prop['id']}（发起方 {prop['creator']}）：{prop['title']}")
            for rnd in range(1, ROUNDS + 1):
                log(f"\n  —— 第 {rnd} 轮表态（并行盲投）——")

                # 1. 各参与方盲投（只看当前版本 + 历史轮，不看本轮他人）；发起人默认接受不参与
                collected = []
                for pid in PARTICIPANTS:
                    if pid == prop["creator"]:
                        continue
                    state = proposal_state_text(prop, show_current_statements=False)
                    obj, _ = run_agent(decision_prompt(
                        ROLES[pid], state,
                        '{"action": "accept|reject|supplement", "reason": "...", "proposal_text": "（仅 supplement 时给调整后完整正文）"}',
                        "就当前提案表态：accept（同意，reason 留空，不要输出任何说明文字）/ reject（反对，附原因）/ supplement（提出调整）。"
                        "从自身项目约束出发；supplement 时给出调整后的完整提案正文。回答务必简洁。",
                    ))
                    obj = obj or {"action": "accept", "reason": ""}
                    action = obj["action"] if obj["action"] in ("accept", "reject", "supplement") else "accept"
                    body = obj.get("reason", "")
                    if action == "accept":
                        body = ""  # accept 不附加文本
                    if action == "supplement" and obj.get("proposal_text"):
                        body = "补充: " + obj["proposal_text"]
                    collected.append((pid, action, body))
                    log(f"    [{pid}] → {action}" + (f"：{body}" if body else ""))

                # 2. 收齐后统一提交（保证盲投）
                for pid, action, body in collected:
                    c.submit(rid, prop["id"], pid, action, body)
                prop = c.get_proposal(rid, prop["id"])  # 刷新

                # 3. chair 判定
                all_acc = c.all_accepted(rid, prop["id"])
                state = proposal_state_text(prop, show_current_statements=True)
                state += f"\n全员接受？{all_acc}"
                obj, _ = run_agent(decision_prompt(
                    CHAIR_ROLE, state,
                    '{"action": "agree|continue|unresolvable", "guidance": "..."}',
                    "作为主持，判定：agree（全员已接受）/ continue（有分歧，给引导）/ unresolvable（无法达成）。"
                    "已进行 3 轮以上仍未共识时，应视情况判 unresolvable。回答简洁，每字段不超过 100 字。",
                    code=CHAIR_CODE,
                ))
                obj = obj or {"action": "continue", "guidance": "请 base 给出兼容方案"}
                verdict = obj["action"] if obj["action"] in ("agree", "continue", "unresolvable") else "continue"
                guidance = obj.get("guidance", "")
                # 确定性兜底（客户端预判）：未全员接受，不许判 agree
                if verdict == "agree" and not all_acc:
                    verdict = "continue"
                    guidance = (guidance + " " if guidance else "") + "（确定性检查拦截：尚未全员接受，不能判 agree）"
                judged = c.judge(rid, prop["id"], verdict, guidance)  # 服务端亦兜底（未全员接受判 agree → 400）
                actual = judged["judgements"][-1]["verdict"]
                log(f"\n    [chair] 判定 → {actual}：{guidance}")

                if judged["state"] == "agreed":
                    log(f"    ✓ 提案 {prop['id']} 达成")
                    break
                if judged["state"] == "unresolvable":
                    log(f"    ✗ 提案 {prop['id']} 无法达成（如实记录）")
                    break

                # 4. continue → 发起方调整出新版本
                obj, _ = run_agent(decision_prompt(
                    f"{ROLES[prop['creator']]}（发起方）", proposal_state_text(prop, True),
                    '{"proposal_text": "调整后的完整提案正文（含代码/伪代码）"}',
                    f"你是发起方，吸收各方反对/补充，给出完整方案作为新版本：说清签名/字段/流转/输入输出/边界，附代码或伪代码。chair 引导：{guidance}。",
                    code=CREATOR_CODE,
                ))
                new_body = (obj or {}).get("proposal_text", "")
                if not new_body:
                    new_body = prop["body"] + "（补充：增加新接口 Y 以兼容，保留原 X 不变）"
                c.revise(rid, prop["id"], new_body, author=prop["creator"])
                prop = c.get_proposal(rid, prop["id"])
                log(f"    [base] 提出新版本 v{prop['version']}：{new_body}")

            # 轮次耗尽仍未收敛 → 判无法达成
            prop = c.get_proposal(rid, prop["id"])
            if prop["state"] == "open":
                c.judge(rid, prop["id"], "unresolvable", "达到轮次上限，无法达成")
                log(f"    ✗ 提案 {prop['id']} 达到轮次上限，判无法达成")

        # 5. 决议汇编 + finalize
        log(f"\n{'─' * 60}\n决议汇编")
        room = c.get_room(rid)
        summary = [f"{p['id']} v{p['version']} → {p['state']}" for p in room["proposals"]]
        obj, _ = run_agent(decision_prompt(
            CHAIR_ROLE, "各提案状态：\n" + "\n".join(summary),
            '{"resolution": "..."}',
            "汇编最终决议：分工（哪个项目做什么）、共识决议（用提案编号+修订号指代）、未决项（如有）。",
            code=CHAIR_CODE,
        ))
        resolution = (obj or {}).get("resolution", "一致通过各提案，按分工执行。")
        c.finalize(rid, resolution)
        log(f"  chair 决议：\n{resolution}")
        log(f"  会议状态 → {c.get_room(rid)['state']}")

        # 6. 决议 → 自动生成 issue（每个参与方一个分工 issue）
        log(f"\n{'─' * 60}\n决议 → 生成 issue")
        for pid in PARTICIPANTS:
            iss = c.create_issue(pid, f"执行决议：{room['title']}", resolution, creator=CHAIR)
            log(f"  → {iss['id']} 指派给 {pid}（决议来源）")

        log("\n" + "=" * 70)
        log("最终会议状态:")
        log(f"  {rid} [{c.get_room(rid)['state']}] {room['title']}")
        for p in c.get_room(rid)["proposals"]:
            log(f"    - 提案 {p['id']} v{p['version']} [{p['state']}]")
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
