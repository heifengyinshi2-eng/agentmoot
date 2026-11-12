"""场景 1：跨项目 issue 闭环（带 Agent，走 HTTP 服务交互）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import start_server  # noqa: E402
from agents import run_agent, decision_prompt  # noqa: E402

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".moot-serve-issue")
PORT = 18087


def log(*a):
    print(*a)


def main():
    proc, c = start_server(STORE, PORT)
    try:
        c.register_project("base-lib", name="JSON 序列化库", superior="human")
        c.register_project("dep-app", name="依赖 base-lib 的 Web 应用", superior="human")

        log("=" * 70)
        log("【场景1】dep-app 给 base-lib 提 issue，base-lib 维护者评审并解决（走 HTTP 服务）")
        log("=" * 70)

        # 1. A 创建 issue
        obj, _ = run_agent(decision_prompt(
            "dep-app 项目 Agent", "（无历史）",
            '{"title": "...", "body": "..."}',
            "你发现依赖的 JSON 序列化库 base-lib 有一个 bug：序列化大整数（超过 2^53）时精度丢失。"
            "请以 issue 形式向 base-lib 反馈，标题一句话、正文含复现步骤与期望行为。",
        ))
        obj = obj or {"title": "大整数序列化精度丢失", "body": "序列化超过 2^53 的整数时精度丢失，期望无损。"}
        iss = c.create_issue("base-lib", obj["title"], obj["body"], creator="dep-app")
        log(f"\n[dep-app] 创建 issue {iss['id']}: {iss['title']}")
        log(f"  正文: {iss['body']}")

        # 2. B 评审
        state = f"issue {iss['id']}: {iss['title']}\n正文: {iss['body']}"
        obj, _ = run_agent(decision_prompt(
            "base-lib 维护者 Agent", state,
            '{"action": "accept|reject|duplicate", "reason": "..."}',
            "评审这个 issue：判定是 accept（有效要修）/ reject（不是问题）/ duplicate（重复）。",
        ))
        obj = obj or {"action": "accept", "reason": "确认为大整数精度问题"}
        _map = {"accept": "accepted", "reject": "rejected", "duplicate": "duplicate",
                "accepted": "accepted", "rejected": "rejected"}
        verdict = _map.get(obj.get("action"), "accepted")
        c.review_issue(iss["id"], verdict, obj.get("reason", ""))
        log(f"\n[base-lib] 评审 → {verdict}（{obj.get('reason','')}）")

        if verdict != "accepted":
            log(f"\n[系统] issue 被 {verdict}，流程到此（维护者最终决定权）。")
            log("\n" + "=" * 70)
            log(f"最终 issue 状态: {iss['id']} [{c.get_issue(iss['id'])['state']}] {iss['title']}")
            return

        # 3. B 解决（维护者决定完成）
        obj, _ = run_agent(decision_prompt(
            "base-lib 维护者 Agent", state,
            '{"summary": "..."}',
            "给出解决方案摘要（说明修复方式与对使用方的影响）。",
        ))
        obj = obj or {"summary": "大整数改为字符串表示，新增无损模式"}
        c.resolve_issue(iss["id"], body=obj.get("summary", ""))
        log(f"\n[base-lib] resolve → {obj.get('summary','')}")

        # 4. A 验收
        obj, _ = run_agent(decision_prompt(
            "dep-app 项目 Agent",
            f"issue {iss['id']} 已被 base-lib 解决：{obj.get('summary','')}",
            '{"action": "accept|new_issue", "comment": "..."}',
            "验收这个解决结果：accept（认可）或 new_issue（发现问题需另提）。",
        ))
        obj = obj or {"action": "accept", "comment": "验收通过"}
        c.comment_issue(iss["id"], obj.get("comment", "验收通过"), author="dep-app")
        log(f"\n[dep-app] 验收 → {obj.get('action')}：{obj.get('comment','')}")

        if obj.get("action") == "accept":
            c.close_issue(iss["id"])
            log(f"\n[系统] issue {iss['id']} 关闭 → {c.get_issue(iss['id'])['state']}")

        log("\n" + "=" * 70)
        log("最终 issue 状态:")
        log(f"  {iss['id']} [{c.get_issue(iss['id'])['state']}] {iss['title']}")
        for cm in c.get_issue(iss["id"])["comments"]:
            log(f"    - {cm['author']}: {cm['body']}")
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
