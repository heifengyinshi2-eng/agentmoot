"""demo 共用：起一个本机 moot 服务并返回 HTTP 客户端。"""
import os
import shutil
import subprocess
import sys
import time

from moot.client import MootClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def start_server(store_dir, port, cleanup=True):
    """起后台 moot 服务，轮询就绪后返回 (proc, client)。"""
    if cleanup and os.path.exists(store_dir):
        shutil.rmtree(store_dir)
    os.makedirs(store_dir, exist_ok=True)

    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "moot.server", "--store", store_dir, "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )

    client = MootClient(f"http://127.0.0.1:{port}")
    ready = False
    for _ in range(100):  # 轮询 /health，命中即退出，上限 30s
        try:
            ready = client.health().get("ok") is True
        except Exception:
            pass
        if ready:
            break
        time.sleep(0.3)
    if not ready:
        proc.terminate()
        raise RuntimeError(f"moot 服务未能就绪 (port={port})")
    return proc, client
