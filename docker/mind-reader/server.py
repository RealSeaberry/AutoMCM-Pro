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

app = FastAPI(title="CUMCM-Master Mind-Reader")
app.mount("/static", StaticFiles(directory="static"), name="static")

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
        if event.is_directory:
            return
        path = Path(event.src_path)
        self.loop.call_soon_threadsafe(
            asyncio.ensure_future,
            self._dispatch(path)
        )

    async def _dispatch(self, path: Path):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        if self._last.get(str(path)) == content:
            return
        self._last[str(path)] = content

        if path == THOUGHT_FILE:
            await broadcast({"type": "thought", "content": content, "ts": _now()})
        elif path == EVAL_FILE:
            await broadcast({"type": "eval", "content": content, "ts": _now()})
        elif path == ITER_FILE:
            try:
                state = json.loads(content)
                await broadcast({"type": "state", "state": state, "ts": _now()})
            except json.JSONDecodeError:
                pass
        elif path == PIPELINE_FILE:
            try:
                pipeline = json.loads(content)
                await broadcast({"type": "pipeline", "pipeline": pipeline, "ts": _now()})
            except json.JSONDecodeError:
                pass
        elif path == REVIEW_FILE:
            await broadcast({"type": "review", "content": content, "ts": _now()})
        elif path == HUMAN_FILE:
            # Detect approval/rework signals and broadcast alert
            if "[APPROVED]" in content:
                await broadcast({"type": "human_signal", "signal": "APPROVED", "ts": _now()})
            elif "[REWORK]" in content:
                await broadcast({"type": "human_signal", "signal": "REWORK", "ts": _now()})


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

    # 监听 memory/ 和 state/ 目录
    observer = Observer()
    watch_dirs = {
        str(THOUGHT_FILE.parent),       # memory/
        str(PIPELINE_FILE.parent),      # state/
        str(WORKSPACE),
    }
    for d in watch_dirs:
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
