"""媒体库：扫描与统计。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import MessageOut, ScanRequest, TaskOut
from app.services import library
from app.services.task_queue import task_queue

router = APIRouter(prefix="/api/library", tags=["library"])


@router.post("/scan", response_model=TaskOut, summary="创建媒体库扫描任务")
def trigger_scan(payload: Optional[ScanRequest] = None, db: Session = Depends(get_db)) -> dict:
    payload = payload or ScanRequest()
    try:
        task = task_queue.enqueue(
            db,
            "scan",
            params={"directory": payload.directory, "recursive": payload.recursive},
            source_path=payload.directory,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return task.to_dict()


@router.get("/stats", summary="媒体库统计")
def stats(db: Session = Depends(get_db)) -> dict:
    data = library.library_stats(db)
    data["media_dirs"] = settings.media_dirs
    return data


@router.get("/dirs", summary="已配置的媒体目录")
def dirs() -> dict:
    return {
        "media_dirs": settings.media_dirs,
        "recursive": settings.scan_recursive,
        "scan_thumbnails": settings.scan_thumbnails,
        "transcode_dir": str(settings.transcode_dir),
        "cache_dir": str(settings.cache_dir),
    }


@router.post("/prune", response_model=MessageOut, summary="清理源文件已不存在的媒体记录")
def prune(db: Session = Depends(get_db)) -> dict:
    from pathlib import Path

    from app import models

    removed = 0
    for item in db.query(models.MediaItem).all():
        if not Path(item.path).exists():
            db.delete(item)
            removed += 1
    db.commit()
    return {"ok": True, "message": f"已清理 {removed} 条失效记录"}
