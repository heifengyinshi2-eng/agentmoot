"""确定性演示：秒级跑通 issue + room 完整流程（无 LLM，用于验证状态机与流程骨架）。"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from moot.store import Store  # noqa: E402

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".moot")


def log(*a):
    print(*a)


def main():
    if os.path.exists(STORE):
        shutil.rmtree(STORE)
    s = Store(STORE)

    # ── 场景1：issue 闭环 ──
    log("=" * 70)
    log("【场景1】issue：dep-app → base-lib（点对点异步）")
    log("=" * 70)
    s.register_project("base-lib", name="JSON 序列化库")
    s.register_project("dep-app", name="依赖方 Web 应用")

    iss = s.create_issue("base-lib", "大整数序列化精度丢失",
                         "序列化 >2^53 整数时精度丢失，期望无损。", creator="dep-app")
    log(f"[dep-app] 创建 {iss['id']}: {iss['title']}（{iss['state']}）")
    s.review_issue(iss["id"], "accepted", reason="确认是 bug")
    log(f"[base-lib] 评审 → accepted")
    s.resolve_issue(iss["id"], body="大整数改为字符串表示，新增无损模式")
    log(f"[base-lib] resolve → 大整数改为字符串表示")
    s.comment_issue(iss["id"], "验收通过", author="dep-app")
    log(f"[dep-app] 验收 → 通过")
    s.close_issue(iss["id"])
    log(f"[系统] {iss['id']} → {s._issue(iss['id'])['state']}\n")

    # ── 场景2：room 收敛 ──
    log("=" * 70)
    log("【场景2】room：三方会议（base/mw/app + chair）")
    log("=" * 70)
    s.register_project("base", name="基础功能维护者")
    s.register_project("mw", name="中间件维护者")
    s.register_project("app", name="应用集成者")

    room = s.create_room("大整数接口变更协调", ["base", "mw", "app"], "facilitator", [
        {"title": "X 接口参数 int 改 string", "body": "base 提议把 X 接口参数从 int 改为 string。", "creator": "base"}
    ])
    rid = room["id"]
    prop = room["proposals"][0]
    log(f"[系统] 会议 {rid} 创建，参与方 base/mw/app，chair=facilitator\n")

    # 第 1 轮：并行盲投（base 为发起人，默认接受，不参与）
    log(f"  提案 {prop['id']} v1 第 1 轮表态（发起人 base 默认接受）：")
    s.submit(rid, "P1", "mw", "reject", "中间件依赖 X 的 int 语义，不能直接改")
    s.submit(rid, "P1", "app", "supplement", "建议新增 string 分支，保留 int 兼容")
    for pid in ("mw", "app"):
        st = [x for x in s._proposal(s._room(rid), "P1")["statements"] if x["author"] == pid][0]
        log(f"    [{pid}] {st['action']}: {st['body']}")
    log("    [base] accept（发起人默认，不表态）")
    s.judge(rid, "P1", "continue", "请 base 给出兼容方案")
    log(f"    [chair] → continue：请 base 给出兼容方案\n")

    # 发起方调整
    s.revise(rid, "P1", "X 参数改为 int|string 联合类型：int 保留原语义，string 分支承载大整数", author="base")
    log(f"  [base] 新版本 v2：X 参数改为 int|string 联合类型\n")

    # 第 2 轮：非发起人全员接受
    log(f"  提案 {prop['id']} v2 第 2 轮表态：")
    for pid in ("mw", "app"):
        s.submit(rid, "P1", pid, "accept", "")
    log("    [mw/app] 显式 accept；[base] 发起人默认 accept")
    log(f"    全员接受？{s.all_accepted(rid, 'P1')}")
    s.judge(rid, "P1", "agree")
    log(f"    [chair] → agree（提案达成）\n")

    # 决议 + 生成 issue
    resolution = "一致通过 P1 v2：base 实现 int|string 联合类型，mw 透传 string，app 按类型分支解析。"
    s.finalize(rid, resolution)
    log(f"[chair] 决议：{resolution}")
    log(f"[系统] 会议 → {s._room(rid)['state']}\n")

    log("决议 → 生成 issue：")
    for pid in ("base", "mw", "app"):
        i = s.create_issue(pid, f"执行决议：{room['title']}", resolution, creator="facilitator")
        log(f"    {i['id']} → {pid}（决议来源）")

    log("\n" + "=" * 70)
    log("最终状态：")
    log(f"  issue  {iss['id']} [{s._issue(iss['id'])['state']}]")
    log(f"  room   {rid} [{s._room(rid)['state']}]  提案 {[p['state'] for p in s._room(rid)['proposals']]}")


if __name__ == "__main__":
    main()
