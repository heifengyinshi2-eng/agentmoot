"""启动 moot HTTP 服务（REST + MCP `/mcp` + SSE `/events` + Web UI `/`）。

用法（包内参考启动方式；部署方法暂不提供）：
    cd <包目录>
    python -m moot.serve --store /path/to/moot-data --port 18080
"""
import argparse

from moot.server import serve


def main():
    ap = argparse.ArgumentParser(description="moot server")
    ap.add_argument("--store", required=True, help="状态存储目录")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18080)
    a = ap.parse_args()
    serve(a.store, a.host, a.port)


if __name__ == "__main__":
    main()
