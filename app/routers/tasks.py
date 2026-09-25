"""任务队列接口：转码 / 抽音轨 / 截图 / 状态查询 / 取消。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db
from app.routers.media import get_media_or_404
from app.schemas import (
    ExtractAudioRequest,
    MessageOut,
    ScreenshotRequest,
    TaskListOut,
    TaskOut,
    TranscodeRequest,
)
from app.services.task_queue import task_queue
from app.utils import ffmpeg_utils

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _resolve_source(db: Session, media_id: Optional[int], path: Optional[str]) -> tuple:
    """定位源文件，返回 ``(source_path, media_item_or_None)``。"""
    if media_id:
        item = get_media_or_404(db, media_id)
        source = Path(item.path)
        if not source.exists():
            raise HTTPException(status_code=404, detail="源文件不存在")
        return source, item
    if path:
        source = Path(path).expanduser()
        if not source.is_absolute():
            raise HTTPException(status_code=400, detail="path 必须是绝对路径")
        if not source.exists():
            raise HTTPException(status_code=404, detail=f"文件不存在：{source}")
        if not ffmpeg_utils.is_media(source):
            raise HTTPException(status_code=400, detail=f"不支持的媒体格式：{source.suffix}")
        item = db.query(models.MediaItem).filter(models.MediaItem.path == str(source)).first()
        return source, item
    raise HTTPException(status_code=400, detail="必须提供 media_id 或 path")


def _output_path(source: Path, output_name: Optional[str], suffix: str,
                 media_type_hint: str = "") -> Path:
    target_dir = settings.transcode_dir / media_type_hint if media_type_hint else settings.transcode_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = output_name or f"{source.stem}{suffix}"
    if not Path(name).suffix:
        name = f"{name}{suffix}"
    return target_dir / name


def _enqueue(db: Session, task_type: str, params: dict, source: Path, output: Path) -> dict:
    task = task_queue.enqueue(
        db, task_type, params=params, source_path=str(source), output_path=str(output)
    )
    return task.to_dict()


# --------------------------------------------------------------------------- #
# 提交任务
# --------------------------------------------------------------------------- #
@router.post("/transcode", response_model=TaskOut, summary="提交转码任务")
def create_transcode(payload: TranscodeRequest, db: Session = Depends(get_db)) -> dict:
    source, item = _resolve_source(db, payload.media_id, payload.path)

    suffix = Path(source).suffix.lower()
    if suffix in (".mp4", ".m4v", ".mov", ".webm", ".mkv"):
        out_suffix = suffix
    elif ffmpeg_utils.classify(source) == "audio":
        out_suffix = ".m4a"
    else:
        out_suffix = ".mp4"

    output = _output_path(source, payload.output_name, out_suffix, media_type_hint="transcode")
    params = {
        "source_path": str(source),
        "output_path": str(output),
        "vcodec": payload.vcodec,
        "acodec": payload.acodec,
        "crf": payload.crf,
        "preset": payload.preset,
        "scale": payload.scale,
        "audio_bitrate": payload.audio_bitrate,
        "duration": float(item.duration) if item is not None else 0.0,
        "media_id": payload.media_id,
    }
    return _enqueue(db, "transcode", params, source, output)


@router.post("/extract-audio", response_model=TaskOut, summary="提交抽音轨任务")
def create_extract_audio(payload: ExtractAudioRequest, db: Session = Depends(get_db)) -> dict:
    source, item = _resolve_source(db, payload.media_id, payload.path)

    suffix_map = {
        "libmp3lame": ".mp3",
        "mp3": ".mp3",
        "aac": ".m4a",
        "libopus": ".opus",
        "opus": ".opus",
        "flac": ".flac",
        "pcm_s16le": ".wav",
        "copy": ".mka",
    }
    out_suffix = suffix_map.get(payload.acodec, ".mp3")
    output = _output_path(source, payload.output_name, out_suffix, media_type_hint="audio")
    params = {
        "source_path": str(source),
        "output_path": str(output),
        "acodec": payload.acodec,
        "bitrate": payload.bitrate,
        "duration": float(item.duration) if item is not None else 0.0,
        "media_id": payload.media_id,
    }
    return _enqueue(db, "extract_audio", params, source, output)


@router.post("/screenshot", response_model=TaskOut, summary="提交截图任务")
def create_screenshot(payload: ScreenshotRequest, db: Session = Depends(get_db)) -> dict:
    source, item = _resolve_source(db, payload.media_id, payload.path)

    output = _output_path(source, payload.output_name, ".jpg", media_type_hint="frames")
    params = {
        "source_path": str(source),
        "output_path": str(output),
        "at": payload.at,
        "width": payload.width,
        "media_id": payload.media_id,
    }
    return _enqueue(db, "screenshot", params, source, output)


@router.post("/scan", response_model=TaskOut, summary="提交媒体库扫描任务")
def create_scan(directory: Optional[str] = Query(default=None),
                recursive: Optional[bool] = Query(default=None),
                db: Session = Depends(get_db)) -> dict:
    task = task_queue.enqueue(
        db, "scan", params={"directory": directory, "recursive": recursive}, source_path=directory
    )
    return task.to_dict()


# --------------------------------------------------------------------------- #
# 查询 / 取消
# --------------------------------------------------------------------------- #
@router.get("", response_model=TaskListOut, summary="任务列表")
def list_tasks(
    status: Optional[str] = Query(default=None, description="pending/running/success/failed/canceled"),
    task_type: Optional[str] = Query(default=None, description="scan/transcode/extract_audio/screenshot"),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(models.Task)
    if status:
        query = query.filter(models.Task.status == status)
    if task_type:
        query = query.filter(models.Task.task_type == task_type)
    total = query.count()
    items = query.order_by(models.Task.id.desc()).limit(limit).all()
    return {"total": total, "items": [item.to_dict() for item in items]}


@router.get("/{task_id}", response_model=TaskOut, summary="任务详情 / 进度查询")
def get_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(models.Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在：id={task_id}")
    return task.to_dict()


@router.post("/{task_id}/cancel", response_model=MessageOut, summary="取消任务")
def cancel_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(models.Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在：id={task_id}")
    if task.status in ("success", "failed", "canceled"):
        return {"ok": False, "message": f"任务已处于终态（{task.status}），无法取消"}

    task_queue.cancel(task_id)
    if task.status == "pending":
        task.status = "canceled"
        db.commit()
    return {"ok": True, "message": f"已请求取消任务 {task_id}"}


@router.delete("/{task_id}", response_model=MessageOut, summary="删除任务记录")
def delete_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(models.Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在：id={task_id}")
    if task.status == "running":
        raise HTTPException(status_code=409, detail="任务正在运行，请先取消再删除")
    db.delete(task)
    db.commit()
    return {"ok": True, "message": f"已删除任务记录 {task_id}"}
