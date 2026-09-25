"""健康检查与运行状态。"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db
from app.services.task_queue import task_queue
from app.utils import ffmpeg_utils

router = APIRouter(prefix="/api", tags=["health"])

_START_TIME = time.time()
_STATUS_KEYS = ("pending", "running", "success", "failed", "canceled")


@router.get("/health", summary="健康检查")
def health(db: Session = Depends(get_db)) -> dict:
    tools = ffmpeg_utils.get_tool_versions()
    database_ok = True
    try:
        db.query(func.count(models.MediaItem.id)).scalar()
    except Exception:  # noqa: BLE001
        database_ok = False

    task_rows = db.query(models.Task.status, func.count(models.Task.id)).group_by(models.Task.status).all()
    task_stats = {str(status): int(count) for status, count in task_rows}

    ffmpeg_ok = bool(tools["ffmpeg"]["available"] and tools["ffprobe"]["available"])
    status = "ok" if (ffmpeg_ok and database_ok) else "degraded"

    return {
        "status": status,
        "app": settings.app_name,
        "version": settings.version,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "database": "ok" if database_ok else "error",
        "media_count": int(db.query(func.count(models.MediaItem.id)).scalar() or 0) if database_ok else 0,
        "tasks": {key: task_stats.get(key, 0) for key in _STATUS_KEYS},
        "task_queue": {
            "workers": task_queue.worker_count,
            "pending_in_memory": task_queue.pending_count(),
        },
        "ffmpeg": tools["ffmpeg"],
        "ffprobe": tools["ffprobe"],
        "media_dirs": settings.media_dirs,
    }


@router.get("/health/ping", summary="轻量探活")
def ping() -> dict:
    return {"pong": True, "app": settings.app_name}
