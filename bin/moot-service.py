"""moot 本机服务守护进程：启动 moot.server，崩溃自动重启（限速）。

开机自启入口：启动文件夹（Startup）里的 start-moot.cmd 拉起本脚本（见 README「本机部署」）。
"""
import subprocess
import os
import socket
import sys
import time

# 当前解释器：venv\Scripts\moot.exe（pythonw 改名，无控制台窗口）
PY = sys.executable
# bin/ 的父目录 = 项目根（用绝对路径启动本脚本以保 __file__ 为绝对路径）
CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(os.environ.get("LOCALAPPDATA", "") or ".", "moot")
PORT = os.environ.get("MOOT_PORT", "18080")


def port_open(port):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def log(f, msg):
    f.write(("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)).encode("utf-8"))


def main():
    log_path = os.path.join(STORE, "moot-service.log")
    # 启动前检查：端口已监听说明已有实例在跑，直接退出（避免重复登录/重复启动冲突）
    if port_open(PORT):
        with open(log_path, "ab") as f:
            log(f, "端口 %s 已被占用（已有实例在跑），本实例退出" % PORT)
        return
    while True:
        f = open(log_path, "ab")
        log(f, "starting moot.server --store %s --port %s" % (STORE, PORT))
        f.flush()
        try:
            p = subprocess.Popen(
                [PY, "-m", "moot.server", "--store", STORE, "--port", PORT],
                cwd=CWD, stdout=f, stderr=subprocess.STDOUT,
            )
        except Exception as e:  # noqa: BLE001
            log(f, "启动失败: %r" % (e,))
            f.close()
            time.sleep(10)
            continue
        rc = p.wait()
        log(f, "moot.server exited code=%s, 3s 后重启" % rc)
        f.close()
        time.sleep(3)


if __name__ == "__main__":
    main()
