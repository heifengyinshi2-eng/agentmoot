"""moot CLI —— argparse 命令入口。"""
import argparse
import json
import os
import sys

from .store import Store, StoreError


def get_store(args):
    root = args.store or os.environ.get("MOOT_HOME") or os.path.join(os.getcwd(), ".moot")
    return Store(root)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_init(args):
    root = args.store or os.environ.get("MOOT_HOME") or os.path.join(os.getcwd(), ".moot")
    os.makedirs(root, exist_ok=True)
    s = Store(root)
    print(f"moot store 初始化于 {root}")


def cmd_project(args):
    s = get_store(args)
    if args.sub == "register":
        s.register_project(args.id, args.name, args.superior)
        print(f"registered {args.id}")
    elif args.sub == "list":
        out(s.list_projects())


def cmd_issue(args):
    s = get_store(args)
    if args.sub == "create":
        iss = s.create_issue(args.assignee, args.title, args.body, args.creator)
        print(iss["id"])
    elif args.sub == "list":
        issues = list(s.state["issues"].values())
        if args.assignee:
            issues = [i for i in issues if i["assignee"] == args.assignee]
        out(issues)
    elif args.sub == "show":
        out(s._issue(args.id))
    elif args.sub == "review":
        verdict = "accepted" if args.accept else "rejected" if args.reject else "duplicate"
        s.review_issue(args.id, verdict, args.reason or "")
        print(f"{args.id} -> {verdict}")
    elif args.sub == "resolve":
        s.resolve_issue(args.id, args.body or "")
        print(f"{args.id} -> resolved")
    elif args.sub == "close":
        s.close_issue(args.id)
        print(f"{args.id} -> closed")
    elif args.sub == "comment":
        s.comment_issue(args.id, args.body, args.author)
        print(f"commented {args.id}")


def cmd_room(args):
    s = get_store(args)
    if args.sub == "create":
        agenda = json.load(open(args.agenda, encoding="utf-8"))
        room = s.create_room(args.title, args.participants.split(","), args.chair, agenda)
        print(room["id"])
    elif args.sub == "list":
        out(list(s.state["rooms"].values()))
    elif args.sub == "show":
        out(s._room(args.id))
    elif args.sub == "submit":
        action = "accept" if args.accept else "reject" if args.reject else "supplement"
        s.submit(args.id, args.proposal, args.author, action, args.body or "")
        print(f"{args.id}/{args.proposal} <- {args.author} {action}")
    elif args.sub == "judge":
        verdict = "agree" if args.agree else "continue" if args.cont else "unresolvable"
        s.judge(args.id, args.proposal, verdict, args.guidance or "")
        print(f"{args.id}/{args.proposal} judge: {verdict}")
    elif args.sub == "revise":
        s.revise(args.id, args.proposal, args.body, args.author)
        print(f"{args.id}/{args.proposal} revised")
    elif args.sub == "finalize":
        resolution = open(args.resolution, encoding="utf-8").read() if args.resolution else (args.body or "")
        s.finalize(args.id, resolution)
        print(f"{args.id} finalized")


def build_parser():
    p = argparse.ArgumentParser(prog="moot", description="Agent 间协作：issue + room")
    p.add_argument("--store", help="moot 存储目录（默认 MOOT_HOME 或 ./.moot）")
    sub = p.add_subparsers(dest="cmd")

    pi = sub.add_parser("init")

    pp = sub.add_parser("project")
    psp = pp.add_subparsers(dest="sub")
    p1 = psp.add_parser("register"); p1.add_argument("id"); p1.add_argument("--name"); p1.add_argument("--superior", default="human")
    p2 = psp.add_parser("list")

    pi2 = sub.add_parser("issue")
    isp = pi2.add_subparsers(dest="sub")
    c = isp.add_parser("create"); c.add_argument("--assignee", required=True); c.add_argument("--title", required=True); c.add_argument("--body", default=""); c.add_argument("--creator", default="")
    l = isp.add_parser("list"); l.add_argument("--assignee")
    sh = isp.add_parser("show"); sh.add_argument("id")
    rv = isp.add_parser("review"); rv.add_argument("id"); g = rv.add_mutually_exclusive_group(required=True); g.add_argument("--accept", action="store_true"); g.add_argument("--reject", action="store_true"); g.add_argument("--duplicate", action="store_true"); rv.add_argument("--reason", default="")
    rs = isp.add_parser("resolve"); rs.add_argument("id"); rs.add_argument("--body", default="")
    cl = isp.add_parser("close"); cl.add_argument("id")
    cm = isp.add_parser("comment"); cm.add_argument("id"); cm.add_argument("--body", required=True); cm.add_argument("--author", default="")

    pr = sub.add_parser("room")
    rsp = pr.add_subparsers(dest="sub")
    rc = rsp.add_parser("create"); rc.add_argument("--title", required=True); rc.add_argument("--participants", required=True); rc.add_argument("--chair", required=True); rc.add_argument("--agenda", required=True)
    rl = rsp.add_parser("list")
    rsh = rsp.add_parser("show"); rsh.add_argument("id")
    rsb = rsp.add_parser("submit"); rsb.add_argument("id"); rsb.add_argument("--proposal", required=True); rsb.add_argument("--author", required=True); g2 = rsb.add_mutually_exclusive_group(required=True); g2.add_argument("--accept", action="store_true"); g2.add_argument("--reject", action="store_true"); g2.add_argument("--supplement", action="store_true"); rsb.add_argument("--body", default="")
    rj = rsp.add_parser("judge"); rj.add_argument("id"); rj.add_argument("--proposal", required=True); g3 = rj.add_mutually_exclusive_group(required=True); g3.add_argument("--agree", action="store_true"); g3.add_argument("--continue", dest="cont", action="store_true"); g3.add_argument("--unresolvable", action="store_true"); rj.add_argument("--guidance", default="")
    rrv = rsp.add_parser("revise"); rrv.add_argument("id"); rrv.add_argument("--proposal", required=True); rrv.add_argument("--body", required=True); rrv.add_argument("--author", default="")
    rf = rsp.add_parser("finalize"); rf.add_argument("id"); rf.add_argument("--resolution"); rf.add_argument("--body", default="")

    p.set_defaults(func=dispatch)

    pserve = sub.add_parser("serve", help="启动 HTTP 服务")
    pserve.add_argument("--host", default="127.0.0.1")
    pserve.add_argument("--port", type=int, default=18080)

    return p


def dispatch(args):
    if args.cmd == "init":
        cmd_init(args)
    elif args.cmd == "project":
        cmd_project(args)
    elif args.cmd == "issue":
        cmd_issue(args)
    elif args.cmd == "room":
        cmd_room(args)
    elif args.cmd == "serve":
        from .server import serve
        root = args.store or os.environ.get("MOOT_HOME") or os.path.join(os.getcwd(), ".moot")
        serve(root, args.host, args.port)
    else:
        print("请指定子命令", file=sys.stderr)


def main():
    p = build_parser()
    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        return
    try:
        dispatch(args)
    except StoreError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
