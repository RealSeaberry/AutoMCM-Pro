#!/usr/bin/env python3
"""
launch_mind_reader.py — 原生（非 Docker）启动 Mind-Reader 实时思维可视化服务器

Docker 版本（docker-compose.yml）依然可用，但要求本机有 Docker；很多沙盒化
的 coding agent runtime 环境里没有 Docker，这个脚本让 agent 自己检测依赖、
按需安装、原生启动，不依赖容器。

用法：
  python scripts/launch_mind_reader.py --check          # 只检查依赖，不启动
  python scripts/launch_mind_reader.py                  # 检查+按需安装依赖，后台启动，打印 URL 就返回
  python scripts/launch_mind_reader.py --foreground      # 前台阻塞运行（Ctrl+C 停止），交互式终端用
  python scripts/launch_mind_reader.py --workspace /path/to/CUMCM_Workspace --port 8090
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / "docker" / "mind-reader" / "server.py"
REQUIREMENTS = REPO_ROOT / "docker" / "mind-reader" / "requirements.txt"
_REQUIRED_MODULES = ("fastapi", "uvicorn", "watchdog", "aiofiles")


def _check_deps() -> list[str]:
    missing = []
    for mod in _REQUIRED_MODULES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return missing


def cmd_check(args):
    missing = _check_deps()
    if not missing:
        print("[mind-reader] ✓ 依赖齐全，可以直接启动")
        return 0
    print(f"[mind-reader] ✗ 缺少依赖: {', '.join(missing)}")
    print(f"  安装命令: {sys.executable} -m pip install -r {REQUIREMENTS}")
    return 1


def _install_deps():
    print("[mind-reader] 安装依赖中...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(REQUIREMENTS)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[mind-reader] ✗ 依赖安装失败:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("[mind-reader] ✓ 依赖安装完成")


def _wait_healthy(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.5)
    return False


def cmd_run(args):
    missing = _check_deps()
    if missing:
        _install_deps()

    workspace = Path(args.workspace).resolve()
    env = {
        "WORKSPACE_DIR":   str(workspace),
        "THOUGHT_FILE":    str(workspace / "memory" / "thought_process.md"),
        "EVAL_FILE":       str(workspace / "memory" / "evaluation_log.md"),
        "ITERATION_FILE":  str(workspace / "memory" / "iteration.json"),
        "PIPELINE_FILE":   str(workspace / "state" / "pipeline.json"),
        "REVIEW_FILE":     str(workspace / "state" / "review_request.md"),
        "HUMAN_FILE":      str(workspace / "state" / "human_intervention.md"),
        "WORKLOG_FILE":    str(workspace / "memory" / "worklog.md"),
        "CITATIONS_FILE":  str(workspace / "memory" / "citations.bib"),
    }
    import os
    full_env = {**os.environ, **env}

    # server.py 里的端口写死在 uvicorn.run(..., port=8080)，用 --port 时改用
    # uvicorn 命令行直接跑，不吃脚本里的默认端口
    cmd = [
        sys.executable, "-m", "uvicorn", "server:app",
        "--host", "0.0.0.0", "--port", str(args.port),
        "--app-dir", str(SERVER_PY.parent),
    ]

    if args.foreground:
        print(f"[mind-reader] 前台运行，工作区: {workspace}")
        print(f"[mind-reader] http://localhost:{args.port}  (Ctrl+C 停止)")
        subprocess.run(cmd, cwd=SERVER_PY.parent, env=full_env)
        return 0

    print(f"[mind-reader] 后台启动中，工作区: {workspace}")
    proc = subprocess.Popen(
        cmd, cwd=SERVER_PY.parent, env=full_env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if _wait_healthy(args.port):
        print(f"[mind-reader] ✓ 已启动，PID={proc.pid}  →  http://localhost:{args.port}")
        print(f"[mind-reader] 停止: kill {proc.pid}")
        return 0
    else:
        print(f"[mind-reader] ✗ 启动超时（15s 内 /health 无响应），PID={proc.pid} 可能已崩溃，"
              f"检查依赖或端口 {args.port} 是否被占用", file=sys.stderr)
        return 1


def main():
    p = argparse.ArgumentParser(description="原生启动 Mind-Reader（不依赖 Docker）")
    p.add_argument("--check", action="store_true", help="只检查依赖，不启动")
    p.add_argument("--workspace", default="CUMCM_Workspace", help="竞赛工作区路径")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--foreground", action="store_true", help="前台阻塞运行（默认后台）")
    args = p.parse_args()

    if args.check:
        sys.exit(cmd_check(args))
    sys.exit(cmd_run(args))


if __name__ == "__main__":
    main()
