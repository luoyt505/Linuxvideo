"""HTTP Range 流式播放。

支持 ``Range: bytes=start-end`` 单区间请求，返回 206 Partial Content；
播放器可据此实现拖动进度条、断点续播。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.routers.media import guess_mime

router = APIRouter(prefix="/api/stream", tags=["stream"])

CHUNK_SIZE = 256 * 1024          # 每次写入 256KB
_RANGE_RE = re.compile(r"bytes=(?P<start>\d*)-(?P<end>\d*)")


def _parse_range(range_header: str, file_size: int) -> Optional[tuple]:
    """解析 Range 头，返回 ``(start, end)``（闭区间，字节）。非法或不支持时返回 None。"""
    match = _RANGE_RE.match((range_header or "").strip())
    if not match:
        return None

    start_text = match.group("start")
    end_text = match.group("end")

    if start_text == "" and end_text == "":
        return None
    if start_text == "":                       # bytes=-500 → 末尾 500 字节
        length = int(end_text)
        if length <= 0:
            return None
        start = max(0, file_size - length)
        end = file_size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1

    if start >= file_size and file_size > 0:
        return None
    end = min(end, file_size - 1)
    if end < start:
        return None
    return start, end


def _file_iterator(path: Path, start: int, end: int, chunk_size: int = CHUNK_SIZE):
    remaining = end - start + 1
    with open(path, "rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/{media_id}", summary="流式播放（支持 Range）")
def stream_media(
    media_id: int,
    request: Request,
    range_header: Optional[str] = Header(default=None, alias="Range"),
    db: Session = Depends(get_db),
):
    item = db.get(models.MediaItem, media_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"媒体条目不存在：id={media_id}")

    source = Path(item.path)
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=404, detail="源文件不存在")

    file_size = source.stat().st_size
    mime = guess_mime(source)
    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{item.filename}"',
        "Cache-Control": "no-cache",
    }

    parsed = _parse_range(range_header, file_size) if range_header else None

    if parsed is None:
        if range_header:
            # 语法正确但不可满足 → 416
            return StreamingResponse(
                iter(()),
                status_code=416,
                headers={**base_headers, "Content-Range": f"bytes */{file_size}"},
                media_type=mime,
            )
        # 无 Range：部分客户端（如 <video>）期望 206 + 完整区间，这里返回 200 全量
        headers = {**base_headers, "Content-Length": str(file_size)}
        return StreamingResponse(
            _file_iterator(source, 0, file_size - 1),
            status_code=200,
            headers=headers,
            media_type=mime,
        )

    start, end = parsed
    headers = {
        **base_headers,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(end - start + 1),
    }
    return StreamingResponse(
        _file_iterator(source, start, end),
        status_code=206,
        headers=headers,
        media_type=mime,
    )


@router.head("/{media_id}", summary="探测流媒体元信息")
def head_stream(media_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(models.MediaItem, media_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"媒体条目不存在：id={media_id}")
    source = Path(item.path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")
    return {
        "id": item.id,
        "filename": item.filename,
        "size": source.stat().st_size,
        "mime": guess_mime(source),
        "duration": item.duration,
        "range_supported": True,
    }


@router.get("/{media_id}/cover", summary="播放页封面（等同缩略图）")
def stream_cover(media_id: int, db: Session = Depends(get_db)):
    item = db.get(models.MediaItem, media_id)
    if item is None or not item.thumbnail_path:
        raise HTTPException(status_code=404, detail="封面不存在")
    thumb = Path(item.thumbnail_path)
    if not thumb.exists():
        raise HTTPException(status_code=404, detail="封面文件不存在")
    return FileResponse(thumb, media_type="image/jpeg")
