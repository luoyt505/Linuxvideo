"""FastAPI 应用入口。

启动：
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
或：
    python -m app.main
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import settings
from app.database import init_db
from app.routers import health, library, media, pages, search, stream, tasks
from app.services.task_queue import task_queue

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mediahub")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：初始化数据库与任务队列。"""
    settings.ensure_dirs()
    init_db()
    task_queue.start()
    logger.info("%s v%s 已启动，媒体目录：%s", settings.app_name, __version__, settings.media_dirs or "（未配置）")
    try:
        yield
    finally:
        task_queue.stop()
        logger.info("%s 已停止", settings.app_name)


app = FastAPI(
    title="mediahub",
    description=(
        "基于 Linux 的多媒体影音中心：媒体库扫描、ffprobe 元数据与封面、"
        "HTTP Range 流式播放、搜索筛选、后台转码队列。"
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

# 路由注册
app.include_router(health.router)
app.include_router(library.router)
app.include_router(media.router)
app.include_router(stream.router)
app.include_router(tasks.router)
app.include_router(search.router)
app.include_router(pages.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """统一参数校验错误响应。"""
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# 静态资源（/static/*），以及 SPA 兜底
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def main() -> None:
    """以 ``python -m app.main`` 方式直接启动开发服务器。"""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
