"""校验项目中所有 mermaid 源码，防止 HTML / 文档里的图因语法错误渲染失败。

数据源：
  1. tools/gen_report.py 里的 ROOM_MERMAID / ISSUE_MERMAID 常量
  2. docs/*.md 里所有 ```mermaid 围栏块

依赖：tools/.mmd-check/node_modules（mermaid + jsdom），由 node check.mjs 完成解析。
用法：python tools/check_mermaid.py
"""
import glob
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHECK_DIR = os.path.join(HERE, ".mmd-check")
CHECK_JS = os.path.join(CHECK_DIR, "check.mjs")


def collect():
    blocks = []

    # 1) gen_report.py 里的 mermaid 常量
    sys.path.insert(0, HERE)
    try:
        import gen_report  # noqa: E402
        for name in ("ROOM_MERMAID", "ISSUE_MERMAID"):
            val = getattr(gen_report, name, None)
            if val:
                blocks.append((f"gen_report.{name}", val))
    except Exception as e:  # pragma: no cover
        print(f"[warn] 无法导入 gen_report.py：{e}")

    # 2) docs/*.md 里的 ```mermaid 围栏块
    for md in sorted(glob.glob(os.path.join(ROOT, "docs", "*.md"))):
        text = open(md, encoding="utf-8").read()
        for i, m in enumerate(re.finditer(r"```mermaid\n(.*?)```", text, re.S), 1):
            blocks.append((f"{os.path.basename(md)}#mermaid{i}", m.group(1)))

    return blocks


def main():
    if not os.path.exists(CHECK_JS):
        print("[error] 缺少 mermaid 校验器，先执行：cd tools/.mmd-check && npm install mermaid jsdom")
        sys.exit(2)

    blocks = collect()
    if not blocks:
        print("[warn] 未找到任何 mermaid 块")
        sys.exit(0)

    tmp = tempfile.mkdtemp(prefix="mmd-check-")
    files = []
    for i, (name, src) in enumerate(blocks):
        p = os.path.join(tmp, f"{i:02d}.mmd")
        with open(p, "w", encoding="utf-8") as f:
            f.write(src)
        files.append(p)

    print(f"校验 {len(blocks)} 个 mermaid 块：")
    proc = subprocess.run(
        ["node", CHECK_JS, *files],
        cwd=CHECK_DIR,
        capture_output=True,
        text=True,
    )
    # 用名称替代临时文件名，便于阅读
    mapping = {os.path.basename(p): blocks[i][0] for i, p in enumerate(files)}
    for line in proc.stdout.splitlines():
        for tmpname, label in mapping.items():
            if tmpname in line:
                line = line.replace(tmpname, label)
                break
        print(line)
    if proc.stderr.strip():
        print(proc.stderr)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
