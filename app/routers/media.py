"""媒体条目：列表、详情、封面、下载、删除。"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import get_db
from app.schemas import MediaItemOut, MediaListOut, MessageOut
from app.utils import ffmpeg_utils

router = APIRouter(prefix="/api/media", tags=["media"])

_SORT_FIELDS = {
    "created_at": models.MediaItem.created_at,
    "updated_at": models.MediaItem.updated_at,
    "title": models.MediaItem.title,
    "filename": models.MediaItem.filename,
    "size": models.MediaItem.size,
    "duration": models.MediaItem.duration,
    "year": models.MediaItem.year,
}

_EXTRA_MIME = {
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".ts": "video/mp2t",
    ".flac": "audio/flac",
    ".opus": "audio/opus",
    ".ape": "audio/x-ape",
    ".m4a": "audio/mp4",
    ".wma": "audio/x-ms-wma",
    ".webp": "image/webp",
    ".heic": "image/heic",
}


def guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _EXTRA_MIME:
        return _EXTRA_MIME[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def get_media_or_404(db: Session, media_id: int) -> models.MediaItem:
    item = db.get(models.MediaItem, media_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"媒体条目不存在：id={media_id}")
    return item


@router.get("", response_model=MediaListOut, summary="媒体列表（分页 / 筛选 / 排序）")
def list_media(
    q: Optional[str] = Query(default=None, description="标题 / 文件名 / 路径关键词"),
    media_type: Optional[str] = Query(default=None, description="video / audio / image"),
    year: Optional[int] = Query(default=None, description="按年份筛选"),
    container: Optional[str] = Query(default=None, description="按容器格式筛选，如 mp4"),
    sort: str = Query(default="created_at", description=f"排序字段：{', '.join(_SORT_FIELDS)}"),
    order: str = Query(default="desc", description="asc / desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(models.MediaItem)

    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.MediaItem.title.ilike(pattern),
                models.MediaItem.filename.ilike(pattern),
                models.MediaItem.path.ilike(pattern),
            )
        )
    if media_type:
        query = query.filter(models.MediaItem.media_type == media_type)
    if year:
        query = query.filter(models.MediaItem.year == year)
    if container:
        query = query.filter(models.MediaItem.container.ilike(f"%{container.strip()}%"))

    total = query.count()

    sort_column = _SORT_FIELDS.get(sort, models.MediaItem.created_at)
    query = query.order_by(sort_column.desc() if order.lower() != "asc" else sort_column.asc())

    items = query.offset((page - 1) * page_size).limit(page_size).all()
    pages = (total + page_size - 1) // page_size if page_size else 0

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "items": [item.to_dict() for item in items],
    }


@router.get("/{media_id}", summary="媒体详情")
def get_media(media_id: int, probe: bool = Query(default=False, description="是否重新运行 ffprobe"),
              db: Session = Depends(get_db)) -> dict:
    item = get_media_or_404(db, media_id)
    data = item.to_dict()
    data["exists"] = Path(item.path).exists()

    if probe and data["exists"]:
        try:
            data["probe"] = ffmpeg_utils.probe_info(item.path)
        except Exception as exc:  # noqa: BLE001
            data["probe_error"] = str(exc)
    return data


@router.delete("/{media_id}", response_model=MessageOut, summary="从媒体库移除记录（不删除源文件）")
def delete_media(media_id: int, db: Session = Depends(get_db)) -> dict:
    item = get_media_or_404(db, media_id)
    if item.thumbnail_path:
        try:
            thumb = Path(item.thumbnail_path)
            if thumb.exists():
                thumb.unlink()
        except OSError:
            pass
    db.delete(item)
    db.commit()
    return {"ok": True, "message": f"已从媒体库移除记录 id={media_id}（源文件未被删除）"}


@router.get("/{media_id}/thumbnail", summary="获取封面（缺失时即时生成）")
def get_thumbnail(media_id: int, db: Session = Depends(get_db)):
    item = get_media_or_404(db, media_id)
    source = Path(item.path)

    dest = Path(item.thumbnail_path) if item.thumbnail_path else ffmpeg_utils.thumbnail_path_for(item.id)
    if not dest.exists():
        if not source.exists() or item.media_type not in ("video", "image"):
            raise HTTPException(status_code=404, detail="该条目没有可用封面")
        try:
            ffmpeg_utils.generate_thumbnail(source, dest, width=settings.thumbnail_width)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"封面生成失败：{exc}") from exc
        item.thumbnail_path = str(dest)
        item.has_thumbnail = True
        db.commit()

    return FileResponse(dest, media_type="image/jpeg")


@router.get("/{media_id}/download", summary="下载源文件")
def download_media(media_id: int, db: Session = Depends(get_db)):
    item = get_media_or_404(db, media_id)
    source = Path(item.path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")
    return FileResponse(
        source,
        media_type=guess_mime(source),
        filename=item.filename,
        headers={"Accept-Ranges": "bytes"},
    )
