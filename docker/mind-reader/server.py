"""
CUMCM-Master Mind-Reader Server
实时推送 AI 内心独白到浏览器
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Set

import aiofiles
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
logger = logging.getLogger("mind-reader")

THOUGHT_FILE  = Path(os.getenv("THOUGHT_FILE",   "CUMCM_Workspace/memory/thought_process.md"))
EVAL_FILE     = Path(os.getenv("EVAL_FILE",     "CUMCM_Workspace/memory/evaluation_log.md"))
ITER_FILE     = Path(os.getenv("ITERATION_FILE","CUMCM_Workspace/memory/iteration.json"))
WORKSPACE     = Path(os.getenv("WORKSPACE_DIR", "CUMCM_Workspace"))
PIPELINE_FILE = Path(os.getenv("PIPELINE_FILE", "CUMCM_Workspace/state/pipeline.json"))
REVIEW_FILE   = Path(os.getenv("REVIEW_FILE",   "CUMCM_Workspace/state/review_request.md"))
HUMAN_FILE    = Path(os.getenv("HUMAN_FILE",    "CUMCM_Workspace/state/human_intervention.md"))
# 2026-08 新增：worklog（§14）/ 引用池（§15）——有专属类型的展示更好看，
# 但即使这两个路径以后又改名/搬家，下面的通用兜底分支仍然会广播出去，
# 不会因为常量写死而漏掉。
WORKLOG_FILE  = Path(os.getenv("WORKLOG_FILE",  "CUMCM_Workspace/memory/worklog.md"))
CITATIONS_FILE = Path(os.getenv("CITATIONS_FILE", "CUMCM_Workspace/memory/citations.bib"))

# _dispatch() 里比较的 path 一律是 resolve() 过的绝对路径（见下方注释），
# 这几个常量也要用同一种绝对形式比较，否则"相对路径写的常量 vs watchdog
# 报上来的绝对路径"永远比不上，会静默全部落进通用兜底分支。
_RESOLVED = {
    "thought": THOUGHT_FILE.resolve(), "eval": EVAL_FILE.resolve(),
    "iter": ITER_FILE.resolve(), "pipeline": PIPELINE_FILE.resolve(),
    "review": REVIEW_FILE.resolve(), "human": HUMAN_FILE.resolve(),
    "worklog": WORKLOG_FILE.resolve(), "citations": CITATIONS_FILE.resolve(),
}

# 固定认识的文件之外，只要落在这些目录树下的变化，都会经通用兜底分支广播——
# Los Alamos 的 hypothesis_tree_*.json / scope_anchor_*.md / paradigm_pool_*.json /
# delphi_round_*.md / ledgers/ / messages/、Kaizen 的自评记录（其实在 pipeline.json
# 里，已经走 pipeline 分支）等，不需要每加一个新文件就回来改一次这个服务器。
_STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="CUMCM-Master Mind-Reader")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# ── WebSocket 连接池 ──────────────────────────────────────────────────────
connections: Set[WebSocket] = set()


async def broadcast(payload: dict):
    dead = set()
    for ws in connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    connections.difference_update(dead)


# ── 文件变化监听 ──────────────────────────────────────────────────────────
class MemoryHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self._last: dict[str, str] = {}

    def on_modified(self, event: FileSystemEvent):
        self._handle(event)

    def on_created(self, event: FileSystemEvent):
        # Los Alamos 产物（hypothesis_tree_*.json 等）首次写入触发的是 created
        # 不是 modified——只挂 on_modified 会漏掉新文件第一次出现的那一刻。
        self._handle(event)

    def _handle(self, event: FileSystemEvent):
        if event.is_directory:
            return
        path = Path(event.src_path)
        self.loop.call_soon_threadsafe(
            asyncio.ensure_future,
            self._dispatch(path)
        )

    async def _dispatch(self, path: Path):
        # watchdog 报的 event.src_path 是不是绝对路径，跟传给 observer.schedule()
        # 的目录字符串风格/操作系统有关，不能假设——统一 resolve() 成绝对路径
        # 再跟下面几个常量比较，避免"同一个文件因为路径写法不同而比对不上、
        # 全部落进通用兜底分支"这种静默降级。
        path = path.resolve()
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        if self._last.get(str(path)) == content:
            return
        self._last[str(path)] = content

        if path == _RESOLVED["thought"]:
            await broadcast({"type": "thought", "content": content, "ts": _now()})
        elif path == _RESOLVED["eval"]:
            await broadcast({"type": "eval", "content": content, "ts": _now()})
        elif path == _RESOLVED["iter"]:
            try:
                state = json.loads(content)
                await broadcast({"type": "state", "state": state, "ts": _now()})
            except json.JSONDecodeError:
                pass
        elif path == _RESOLVED["pipeline"]:
            try:
                pipeline = json.loads(content)
                await broadcast({"type": "pipeline", "pipeline": pipeline, "ts": _now()})
            except json.JSONDecodeError:
                pass
        elif path == _RESOLVED["review"]:
            await broadcast({"type": "review", "content": content, "ts": _now()})
        elif path == _RESOLVED["human"]:
            # Detect approval/rework signals and broadcast alert
            if "[APPROVED]" in content:
                await broadcast({"type": "human_signal", "signal": "APPROVED", "ts": _now()})
            elif "[REWORK]" in content:
                await broadcast({"type": "human_signal", "signal": "REWORK", "ts": _now()})
        elif path == _RESOLVED["worklog"]:
            # 只推最近几行，worklog 会越写越长，没必要每次全量传输
            tail = "\n".join(content.splitlines()[-30:])
            await broadcast({"type": "worklog", "content": tail, "ts": _now()})
        elif path == _RESOLVED["citations"]:
            n_entries = content.count("@")
            await broadcast({"type": "citations", "count": n_entries, "ts": _now()})
        else:
            # 通用兜底——Los Alamos 产物（hypothesis_tree_*.json、scope_anchor_*.md、
            # paradigm_pool_*.json、delphi_round_*.md）、memory/ledgers/、
            # state/messages/ 等任何没有专属分支的文件变化，都走这里广播出去，
            # 前端拿不到"专属展示"但至少能在通用动态流里看到，不会静默丢失。
            try:
                rel = path.relative_to(WORKSPACE.resolve())
            except ValueError:
                rel = path
            snippet = content if len(content) <= 800 else content[:800] + "…（截断）"
            await broadcast({"type": "activity", "path": str(rel), "snippet": snippet, "ts": _now()})


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _read_safe(path: Path, default="") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return default


def _workspace_tree() -> list:
    """返回工作区文件树（最多2层深度）"""
    if not WORKSPACE.exists():
        return []
    result = []
    for item in sorted(WORKSPACE.iterdir()):
        node = {"name": item.name, "is_dir": item.is_dir(), "children": []}
        if item.is_dir():
            for child in sorted(item.iterdir()):
                node["children"].append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": child.stat().st_size if child.is_file() else 0
                })
        result.append(node)
    return result


# ── HTTP 端点 ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    async with aiofiles.open("static/index.html", encoding="utf-8") as f:
        return await f.read()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/pipeline")
async def get_pipeline():
    """返回 GitOps 流水线快照"""
    pipeline = {}
    try:
        pipeline = json.loads(_read_safe(PIPELINE_FILE, "{}"))
    except Exception:
        pass
    return JSONResponse({
        "pipeline": pipeline,
        "review":   _read_safe(REVIEW_FILE),
        "ts":       _now(),
    })


@app.get("/api/snapshot")
async def snapshot():
    """首次加载时返回全量快照"""
    state = {}
    try:
        state = json.loads(_read_safe(ITER_FILE, "{}"))
    except Exception:
        pass
    pipeline = {}
    try:
        pipeline = json.loads(_read_safe(PIPELINE_FILE, "{}"))
    except Exception:
        pass
    return JSONResponse({
        "thought":   _read_safe(THOUGHT_FILE),
        "eval":      _read_safe(EVAL_FILE),
        "state":     state,
        "pipeline":  pipeline,
        "review":    _read_safe(REVIEW_FILE),
        "tree":      _workspace_tree(),
        "ts":        _now(),
    })


@app.get("/api/tree")
async def tree():
    return JSONResponse({"tree": _workspace_tree(), "ts": _now()})


# ── WebSocket ─────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connections.add(ws)
    logger.info(f"Client connected  ({len(connections)} total)")
    try:
        while True:
            await ws.receive_text()   # keep-alive ping
    except WebSocketDisconnect:
        connections.discard(ws)
        logger.info(f"Client disconnected  ({len(connections)} total)")


# ── 启动事件 ──────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    loop = asyncio.get_event_loop()
    handler = MemoryHandler(loop)

    # 监听 memory/ 和 state/ 目录——这两个要递归（Los Alamos 产物落在
    # memory/ledgers/、state/messages/ 这类子目录里，不递归就会漏掉）；
    # workspace 顶层只做非递归监听（主要是给 tree 变化打个补丁，src/latex
    # 底下的编译产物churn没必要全递归进来，避免无意义的 activity 广播刷屏）。
    observer = Observer()
    recursive_dirs = {str(THOUGHT_FILE.parent), str(PIPELINE_FILE.parent)}  # memory/, state/
    shallow_dirs = {str(WORKSPACE)}
    for d in recursive_dirs:
        if Path(d).exists():
            observer.schedule(handler, d, recursive=True)
            logger.info(f"Watching {d} (recursive)")
    for d in shallow_dirs - recursive_dirs:
        if Path(d).exists():
            observer.schedule(handler, d, recursive=False)
            logger.info(f"Watching {d}")

    observer.start()
    logger.info("Mind-Reader server started  →  http://localhost:8080")

    # 定期推送文件树（每 5s）
    async def push_tree():
        while True:
            await asyncio.sleep(5)
            if connections:
                await broadcast({"type": "tree", "tree": _workspace_tree(), "ts": _now()})

    asyncio.ensure_future(push_tree())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=False)
